from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_dialogue_facade_exports_legacy_dialogue_contracts() -> None:
    from rs_core.agent.dialogue import apply_dialogue_plan as facade_apply_dialogue_plan
    from rs_core.agent.dialogue import plan_dialogue_turn as facade_plan_dialogue_turn
    from rs_core.agent.dialogue import apply_dialogue_plan as legacy_apply_dialogue_plan
    from rs_core.agent.dialogue import plan_dialogue_turn as legacy_plan_dialogue_turn

    assert facade_plan_dialogue_turn is legacy_plan_dialogue_turn
    assert facade_apply_dialogue_plan is legacy_apply_dialogue_plan


def test_planner_facade_exports_legacy_planner_contracts() -> None:
    from rs_core.agent.planner import LLMDialoguePlanner as facade_planner
    from rs_core.agent.planner import LLMDialoguePlannerConfig as facade_config
    from rs_core.agent.planner import LLMDialoguePlanner as legacy_planner
    from rs_core.agent.planner import LLMDialoguePlannerConfig as legacy_config

    assert facade_planner is legacy_planner
    assert facade_config is legacy_config


def test_tools_facade_exports_manifest_and_validation_contracts() -> None:
    from rs_core.agent.tools import AGENT_TOOL_MANIFEST as facade_manifest
    from rs_core.agent.tools import build_agent_tool_planner_system_prompt as facade_prompt
    from rs_core.agent.tools import validate_agent_tool_call as facade_validate_tool
    from rs_core.agent.tools import AGENT_TOOL_MANIFEST as legacy_manifest
    from rs_core.agent.tools import build_agent_tool_planner_system_prompt as legacy_prompt
    from rs_core.agent.tools import validate_agent_tool_call as legacy_validate_tool

    assert facade_manifest is legacy_manifest
    assert facade_prompt is legacy_prompt
    assert facade_validate_tool is legacy_validate_tool
    assert {tool.name for tool in facade_manifest} == {tool.name for tool in legacy_manifest}


def test_explanation_facade_exports_public_explanation_contracts() -> None:
    from rs_core.agent.explanation import build_recommendation_explanation as facade_build_explanation
    from rs_core.agent.explanation import latest_recommendation_turn as facade_latest_turn
    from rs_core.agent.explanation import build_recommendation_explanation as legacy_build_explanation
    from rs_core.agent.explanation import latest_recommendation_turn as legacy_latest_turn

    assert facade_build_explanation is legacy_build_explanation
    assert facade_latest_turn is legacy_latest_turn


def test_contracts_facade_exports_recommendation_turn_result() -> None:
    from rs_core.agent.contracts import RecommendationTurnResult as facade_result
    from rs_core.agent.contracts.schema import RecommendationTurnResult as legacy_result

    assert facade_result is legacy_result


def test_feedback_facade_exports_candidate_feedback_contracts() -> None:
    from rs_core.agent.feedback import apply_feedback_to_candidates as facade_apply_feedback
    from rs_core.agent.feedback import apply_feedback_to_candidates as legacy_apply_feedback

    assert facade_apply_feedback is legacy_apply_feedback


def test_inference_facade_exports_optional_policy_contracts() -> None:
    from rs_core.agent.inference import apply_optional_inference_policy as facade_apply_policy
    from rs_core.agent.inference import apply_optional_inference_policy as legacy_apply_policy

    assert facade_apply_policy is legacy_apply_policy


def test_rag_facade_exports_runtime_rag_contracts() -> None:
    from rs_core.agent.rag import SQLiteBM25QueryPlanningRetriever as facade_query_retriever
    from rs_core.agent.rag import build_query_rag_context_for_planning as facade_build_query_context
    from rs_core.agent.rag import SQLiteBM25QueryPlanningRetriever as legacy_query_retriever
    from rs_core.agent.rag import build_query_rag_context_for_planning as legacy_build_query_context

    assert facade_query_retriever is legacy_query_retriever
    assert facade_build_query_context is legacy_build_query_context


def test_agent_policy_facades_export_hybrid_demo_contracts() -> None:
    from rs_core.agent.decision import make_agent_decision as facade_decision
    from rs_core.agent.model_clients import QwenLocalClient as facade_qwen_client
    from rs_core.agent.rerank import apply_feedback_rerank as facade_feedback_rerank
    from rs_core.agent.decision import make_agent_decision as legacy_decision
    from rs_core.agent.rerank import apply_feedback_rerank as legacy_feedback_rerank
    from rs_core.agent.model_clients.qwen_client import QwenLocalClient as legacy_qwen_client

    assert facade_decision is legacy_decision
    assert facade_feedback_rerank is legacy_feedback_rerank
    assert facade_qwen_client is legacy_qwen_client
