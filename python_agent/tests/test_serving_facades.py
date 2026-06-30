from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from rs_core.serving.facades import (
    RecommendationFacade,
    RecallFacade,
    SERVING_GOVERNANCE_GUARDRAILS,
)
from rs_core.serving.schemas import RecallRequest, RecommendFromSequenceRequest
from rs_core.agent.adapters.rag import RagAgentAdapter
from rs_core.workflow.hybrid_environment import _compact_deepfm_output

pytestmark = [pytest.mark.serving, pytest.mark.smoke]

INTERNAL_TOP_LEVEL_FIELDS = {
    "diagnostics",
    "source_scores",
    "tool_traces",
    "ranking",
    "score_trace",
    "governance",
}


class SpyOnlineRecommender:
    def __init__(self) -> None:
        self.retrieve_calls: list[dict[str, Any]] = []
        self.recommend_calls: list[dict[str, Any]] = []

    def tool_retrieve_candidates(
        self,
        user_sequence: dict[str, Any],
        *,
        prior_turn_items: set[str],
        candidate_pool_size: int | None,
    ) -> dict[str, Any]:
        self.retrieve_calls.append({
            "user_sequence": user_sequence,
            "prior_turn_items": prior_turn_items,
            "candidate_pool_size": candidate_pool_size,
        })
        return {
            "candidate_item_ids": ["candidate_1", "candidate_2"],
            "candidate_count": 2,
            "retrieval_summary": {
                "target_pool_size": candidate_pool_size,
                "path_count": 1,
                "supporting_snippets": ["internal evidence"],
                "score_trace": {"candidate_1": 1.0},
            },
            "diagnostics": {"internal_only": True},
            "source_scores": {"candidate_1": 1.0},
            "tool_traces": [{"tool": "retrieve_candidates"}],
        }

    def recommend(
        self,
        user_sequence: dict[str, Any],
        *,
        user_id: str | None,
        feedback_text: str | None,
        top_k: int,
        candidate_pool_size: int | None,
        complete_pool500: bool,
    ) -> SimpleNamespace:
        self.recommend_calls.append({
            "user_sequence": user_sequence,
            "user_id": user_id,
            "feedback_text": feedback_text,
            "top_k": top_k,
            "candidate_pool_size": candidate_pool_size,
            "complete_pool500": complete_pool500,
        })
        return SimpleNamespace(
            request_id="request-1",
            display={
                "schema_version": "rs_agent_display_v1",
                "session_id": "request-1",
                "items": [{"parent_asin": "candidate_1"}],
            },
            items=[{"parent_asin": "candidate_1"}],
            candidate_count=2,
            fallback_used=False,
            diagnostics={"internal_only": True},
            ranking=[{"item_id": "candidate_1", "score": 1.0}],
            tool_traces=[{"tool": "rank_candidates"}],
        )


def test_recall_facade_delegates_to_retriever_and_returns_public_contract_only() -> None:
    recommender = SpyOnlineRecommender()
    facade = RecallFacade(recommender)
    request = RecallRequest(
        user_id="online-u1",
        user_sequence={"recent_item_sequence": ["seed_audio"]},
        prior_turn_items=["already_seen"],
        candidate_pool_size=20,
    )

    response = facade.recall(request)

    assert set(response) == {"request_id", "candidate_item_ids", "candidate_count", "retrieval_summary"}
    assert not INTERNAL_TOP_LEVEL_FIELDS & set(response)
    assert response["candidate_item_ids"] == ["candidate_1", "candidate_2"]
    assert response["candidate_count"] == 2
    assert response["retrieval_summary"] == {"target_pool_size": 20, "path_count": 1}
    assert recommender.retrieve_calls == [{
        "user_sequence": {"recent_item_sequence": ["seed_audio"], "user_id": "online-u1"},
        "prior_turn_items": {"already_seen"},
        "candidate_pool_size": 20,
    }]


def test_recommendation_facade_delegates_to_recommender_and_returns_public_contract_only() -> None:
    recommender = SpyOnlineRecommender()
    facade = RecommendationFacade(recommender)
    request = RecommendFromSequenceRequest(
        user_id="online-u1",
        user_sequence={"recent_item_sequence": ["seed_audio"]},
        feedback_text="prefer bluetooth",
        top_k=1,
        candidate_pool_size=20,
        complete_pool500=True,
    )

    response = facade.recommend_from_sequence(request)

    assert set(response) == {"request_id", "display", "items", "item_count", "candidate_count", "fallback_used"}
    assert not INTERNAL_TOP_LEVEL_FIELDS & set(response)
    assert response["item_count"] == 1
    assert response["items"] == [{"parent_asin": "candidate_1"}]
    assert recommender.recommend_calls == [{
        "user_sequence": {"recent_item_sequence": ["seed_audio"]},
        "user_id": "online-u1",
        "feedback_text": "prefer bluetooth",
        "top_k": 1,
        "candidate_pool_size": 20,
        "complete_pool500": True,
    }]


def test_serving_facade_governance_keeps_forbidden_route_promotions_disabled() -> None:
    assert SERVING_GOVERNANCE_GUARDRAILS == {
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
    }


def test_rag_agent_query_support_boundaries_remain_internal_only() -> None:
    support = RagAgentAdapter().build_query_support(
        query="commute speaker",
        evidence=[{"field": "features", "text": "portable bluetooth"}],
        applied=True,
    ).to_dict()
    boundaries = support["retrieval_hints"]

    assert boundaries["applied"] is True
    assert boundaries["retrieval_scope"] == "query_planning"
    assert boundaries["candidate_generation_allowed"] is False
    assert boundaries["ranking_input_replacement_allowed"] is False
    assert boundaries["promotion_allowed"] is False
    assert boundaries["public_payload_allowed"] is False
    assert support["public_payload_allowed"] is False


def test_deepfm_compact_output_does_not_expose_scores_features_or_diagnostics() -> None:
    output = _compact_deepfm_output({
        "ranked_items": [
            {"item_id": "candidate_1", "deepfm_score": 0.99, "item_features": {"brand": "internal"}},
            {"item_id": "candidate_2", "score": 0.50, "feature_rows": [{"x": 1}]},
        ],
        "diagnostics": {
            "ranker": "cold_deepfm_shadow",
            "candidate_count": 2,
            "return_top_k": 2,
            "feature_rows": [{"x": 1}],
            "label_binary": [1],
        },
    })

    assert output == {
        "ranked_item_ids": ["candidate_1", "candidate_2"],
        "ranked_item_count": 2,
        "ranker": "cold_deepfm_shadow",
        "candidate_count": 2,
        "return_top_k": 2,
    }
    serialized = str(output).lower()
    assert "deepfm_score" not in serialized
    assert "item_features" not in serialized
    assert "feature_rows" not in serialized
    assert "label_binary" not in serialized
