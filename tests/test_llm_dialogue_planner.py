from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

from rs_core.common.io import write_jsonl
from rs_core.common.openai_compatible_client import OpenAICompatibleClient
from rs_core.rsagent.dialogue import plan_dialogue_turn
from rs_core.rsagent.llm_dialogue_planner import (
    LLMDialoguePlanner,
    LLMDialoguePlannerConfig,
    dialogue_plan_from_payload,
)
from rs_core.rsagent.schema import AgentSession
from rs_core.workflow.hybrid_environment import HybridRecommendationEnvironment


def test_llm_dialogue_planner_accepts_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_AGENT_TEST_KEY", "test-key")
    session = AgentSession(session_id="s1", user_id="u1")
    fallback = plan_dialogue_turn("I need home office gear", session)
    client = OpenAICompatibleClient(base_url="https://example.test", api_key_env="RS_AGENT_TEST_KEY", transport=_transport({
        "intent": "recommend_request",
        "action": "recommend_items",
        "assistant_response": "明白，你想搭建实用的 home office。我会优先看办公效率、桌面连接和日常收纳相关的选择。",
        "constraints_update": {"preferred_keywords": {"home office": 1.0, "office": 1.0}},
        "should_recommend": True,
        "tool_calls": [
            {"name": "get_user_context", "phase": "pre_recommendation"},
            {"name": "call_rag_agent", "phase": "pre_recommendation", "arguments": {"stage": "pre_retrieval_query_support", "query": "home office gear"}},
            {"name": "retrieve_candidates", "phase": "pre_recommendation", "arguments": {"query": "home office gear", "retrieval_mode": "specific_need", "target_pool_size": 100}},
            {"name": "rank_candidates", "phase": "post_recommendation", "arguments": {"return_top_k": 20}},
            {"name": "build_recommendation_slate", "phase": "post_recommendation"},
        ],
    }))

    result = LLMDialoguePlanner(LLMDialoguePlannerConfig(enabled=True, mode="active", model="gpt-test"), client).plan("I need home office gear", session, fallback)

    assert result.valid
    assert result.plan is not None
    assert result.plan.intent == "recommend_request"
    assert result.plan.should_recommend is True
    assert result.plan.constraints_update.preferred_keywords["home office"] == 1.0
    assert [call["name"] for call in result.plan.tool_calls] == ["get_user_context", "call_rag_agent", "retrieve_candidates", "rank_candidates", "build_recommendation_slate"]
    rag_call = next(call for call in result.plan.tool_calls if call["name"] == "call_rag_agent")
    assert rag_call["arguments"]["stage"] == "pre_retrieval_query_support"
    assert rag_call["arguments"]["candidate_scope"] == "current_turn_only"


def test_llm_dialogue_planner_falls_back_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_AGENT_TEST_KEY", "test-key")
    session = AgentSession(session_id="s1", user_id="u1")
    fallback = plan_dialogue_turn("I need headphones", session)
    client = OpenAICompatibleClient(base_url="https://example.test", api_key_env="RS_AGENT_TEST_KEY", transport=lambda *_args: {"choices": [{"message": {"content": "not json"}}]})

    result = LLMDialoguePlanner(LLMDialoguePlannerConfig(enabled=True, mode="active", model="gpt-test"), client).plan("I need headphones", session, fallback)

    assert not result.valid
    assert result.plan is None
    assert result.diagnostics["status"] == "fallback"


@pytest.mark.parametrize("payload,error", [
    ({"intent": "buy_now", "action": "recommend_items", "assistant_response": "可以，我会帮你找耳机。"}, "invalid_dialogue_intent"),
    ({"intent": "recommend_request", "action": "recommend_items", "assistant_response": "我会调用 retrieve_candidates 找候选池。"}, "assistant_response_internal_leakage"),
    ({"intent": "recommend_request", "action": "recommend_items", "assistant_response": "可以，我会帮你找耳机。", "tool_calls": [{"name": "raw_sql"}]}, "unknown_tool"),
])
def test_dialogue_plan_from_payload_rejects_invalid_contract(payload: dict[str, Any], error: str) -> None:
    fallback = plan_dialogue_turn("I need headphones", AgentSession(session_id="s1", user_id="u1"))

    with pytest.raises(ValueError, match=error):
        dialogue_plan_from_payload(payload, user_input="I need headphones", fallback_plan=fallback)


def test_llm_dialogue_planner_rejects_low_level_rag_tool_and_arguments() -> None:
    fallback = plan_dialogue_turn("I need headphones", AgentSession(session_id="s1", user_id="u1"))

    with pytest.raises(ValueError, match="unknown_tool:query_rag"):
        dialogue_plan_from_payload({
            "intent": "recommend_request",
            "action": "recommend_items",
            "assistant_response": "可以，我会帮你找耳机。",
            "tool_calls": [{"name": "query_rag", "phase": "pre_recommendation", "arguments": {"query": "headphones"}}],
        }, user_input="I need headphones", fallback_plan=fallback)

    with pytest.raises(ValueError, match="forbidden_call_rag_agent_argument:provider"):
        dialogue_plan_from_payload({
            "intent": "recommend_request",
            "action": "recommend_items",
            "assistant_response": "可以，我会帮你找耳机。",
            "tool_calls": [{"name": "call_rag_agent", "phase": "pre_recommendation", "arguments": {"stage": "pre_retrieval_query_support", "query": "headphones", "provider": "qdrant"}}],
        }, user_input="I need headphones", fallback_plan=fallback)


def test_llm_dialogue_planner_validates_fallback_completion_arguments() -> None:
    fallback = plan_dialogue_turn("I need headphones", AgentSession(session_id="s1", user_id="u1"))
    retrieve_call = next(call for call in fallback.tool_calls if call["name"] == "retrieve_candidates")
    retrieve_call["arguments"]["semantic_mode"] = "hybrid_query_history"

    with pytest.raises(ValueError, match="forbidden_tool_argument:semantic_mode"):
        dialogue_plan_from_payload({
            "intent": "recommend_request",
            "action": "recommend_items",
            "assistant_response": "可以，我会帮你找耳机。",
            "should_recommend": True,
            "tool_calls": [{"name": "get_user_context", "phase": "pre_recommendation"}],
        }, user_input="I need headphones", fallback_plan=fallback)


def test_home_office_current_need_uses_query_and_not_low_level_provider_fields() -> None:
    fallback = plan_dialogue_turn("I am setting up a home office and need practical gear", AgentSession(session_id="s1", user_id="u1"))
    plan = dialogue_plan_from_payload({
        "intent": "recommend_request",
        "action": "recommend_items",
        "assistant_response": "明白，你现在更需要实用的 home office 配置。我会优先看提升办公效率、连接稳定性和桌面整理的商品。",
        "constraints_update": {"preferred_keywords": {"home office": 1.0, "office": 1.0, "desk": 1.0}},
        "should_recommend": True,
        "tool_calls": [{"name": "retrieve_candidates", "phase": "pre_recommendation", "arguments": {"query": "practical home office gear", "retrieval_mode": "specific_need", "profile_usage": "current_need_first", "profile_policy": {"history_weight": "current_query_first"}}}],
    }, user_input="I am setting up a home office and need practical gear", fallback_plan=fallback)

    assert plan.constraints_update.preferred_keywords["home office"] == 1.0
    retrieve_call = next(call for call in plan.tool_calls if call["name"] == "retrieve_candidates")
    assert retrieve_call["arguments"] == {
        "query": "practical home office gear",
        "retrieval_mode": "specific_need",
        "profile_usage": "light",
        "profile_policy": {"history_weight": "light"},
    }


def test_hybrid_environment_shadow_returns_fallback_with_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_AGENT_TEST_KEY", "test-key")
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path, {"enabled": True, "mode": "shadow", "model": "gpt-test", "api_key_env": "RS_AGENT_TEST_KEY"})), limit_users=1)
    monkeypatch.setattr(OpenAICompatibleClient, "chat_completion", _fake_chat_completion({
        "intent": "unsupported",
        "action": "ask_clarifying_question",
        "assistant_response": "你更想优先改善办公效率、桌面整理，还是设备连接？",
        "should_recommend": False,
    }))

    plan = env.plan_dialogue("I need headphones", env.start_session("u1"))

    assert plan.intent == "recommend_request"
    assert plan.diagnostics["llm_dialogue_planner"]["mode"] == "shadow"
    assert plan.diagnostics["llm_dialogue_planner"]["shadow_valid"] is True
    assert plan.diagnostics["llm_dialogue_planner"]["returned_plan"] == "fallback"
    assert "_tool_planner_contract" in plan.diagnostics


def test_hybrid_environment_active_returns_valid_llm_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_AGENT_TEST_KEY", "test-key")
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path, {"enabled": True, "mode": "active", "model": "gpt-test", "api_key_env": "RS_AGENT_TEST_KEY"})), limit_users=1)
    monkeypatch.setattr(OpenAICompatibleClient, "chat_completion", _fake_chat_completion({
        "intent": "unsupported",
        "action": "ask_clarifying_question",
        "assistant_response": "你更想优先改善办公效率、桌面整理，还是设备连接？",
        "should_recommend": False,
    }))

    plan = env.plan_dialogue("make it useful for my room", env.start_session("u1"))

    assert plan.intent == "unsupported"
    assert plan.action == "ask_clarifying_question"
    assert plan.diagnostics["llm_dialogue_planner"]["status"] == "ok"
    assert "_tool_planner_contract" in plan.diagnostics


def test_hybrid_environment_active_falls_back_on_invalid_llm_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_AGENT_TEST_KEY", "test-key")
    env = HybridRecommendationEnvironment.from_config(str(_write_dialogue_fixture(tmp_path, {"enabled": True, "mode": "active", "model": "gpt-test", "api_key_env": "RS_AGENT_TEST_KEY"})), limit_users=1)
    monkeypatch.setattr(OpenAICompatibleClient, "chat_completion", _fake_chat_completion({
        "intent": "buy_now",
        "action": "recommend_items",
        "assistant_response": "可以，我会帮你找耳机。",
    }))

    plan = env.plan_dialogue("I need headphones", env.start_session("u1"))

    assert plan.intent == "recommend_request"
    assert plan.diagnostics["llm_dialogue_planner"]["status"] == "fallback"
    assert plan.diagnostics["llm_dialogue_planner"]["returned_plan"] == "fallback"


def _transport(payload: dict[str, Any]):
    def fake_transport(_url: str, _headers: dict[str, str], _body: dict[str, Any], _timeout: float) -> dict[str, Any]:
        return {"id": "cmpl-test", "model": "gpt-test", "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}, "finish_reason": "stop"}]}
    return fake_transport


def _fake_chat_completion(payload: dict[str, Any]):
    def fake_chat_completion(self: OpenAICompatibleClient, **_kwargs: Any) -> dict[str, Any]:
        return {"id": "cmpl-test", "model": "gpt-test", "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}, "finish_reason": "stop"}]}
    return fake_chat_completion


def _write_dialogue_fixture(root: Path, llm_config: dict[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    clean = root / "clean"
    views = root / "views"
    clean.mkdir()
    views.mkdir()
    write_jsonl(clean / "user_sequences.train.jsonl", [{"user_id": "u1", "recent_item_sequence": ["seed_audio"], "recent_positive_item_sequence": ["seed_audio"]}])
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [])
    write_jsonl(views / "popular_recall.jsonl", [{"parent_asin": "charger_1", "category": "Accessories", "pop_score": 5}])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [{"src_item": "seed_audio", "dst_item": "speaker_1", "score": 2.0, "category": "Audio", "title_clean": "Bluetooth speaker"}])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [{"parent_asin": "seed_audio", "main_category": "Audio"}, {"parent_asin": "speaker_1", "main_category": "Audio"}])
    write_jsonl(views / "category_top_items.jsonl", [])
    config = root / "config.yaml"
    config.write_text(json.dumps({
        "clean_dir": str(clean),
        "views_dir": str(views),
        "output_dir": str(root / "out"),
        "top_k": 3,
        "candidate_pool_size": 10,
        "popular_fallback_count": 3,
        "agent_runtime": {"llm_dialogue_planner": llm_config},
    }), encoding="utf-8")
    return config
