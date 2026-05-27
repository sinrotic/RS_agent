from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from rs_core.display.builder import item_to_display_card, validate_public_display_payload
from rs_core.rsagent.policy import normalize_feedback_input, parse_feedback
from rs_core.rsagent.schema import DisplayResponse
from rs_core.workflow.hybrid_demo import recommend_for_user
from rs_core.workflow.hybrid_environment import HybridRecommendationEnvironment


@dataclass
class OnlineRecommendationResult:
    request_id: str
    display: dict[str, Any]
    items: list[dict[str, Any]]
    candidate_count: int
    fallback_used: bool


class OnlinePool500Recommender:
    def __init__(self, env: HybridRecommendationEnvironment) -> None:
        self.env = env

    @classmethod
    def from_environment(cls, env: HybridRecommendationEnvironment) -> OnlinePool500Recommender:
        return cls(env)

    def recommend(
        self,
        user_sequence: dict[str, Any],
        *,
        user_id: str | None = None,
        feedback_text: str | None = None,
        top_k: int = 5,
        candidate_pool_size: int | None = None,
        complete_pool500: bool = False,
    ) -> OnlineRecommendationResult:
        if complete_pool500:
            raise ValueError("complete_pool500 is not available in the online request path yet")
        request_id = str(uuid4())
        normalized_sequence = _normalize_sequence(user_sequence, user_id)
        config = _request_config(self.env.config, top_k=top_k, candidate_pool_size=candidate_pool_size)
        feedback_constraints = None
        if feedback_text:
            feedback_constraints = parse_feedback(normalize_feedback_input(feedback_text))
        result = recommend_for_user(
            normalized_sequence,
            self.env.popular,
            self.env.itemcf_weak,
            self.env.itemcf_strong,
            self.env.category_top,
            self.env.item_category,
            config,
            semantic_index=self.env.semantic_index,
            feedback_constraints=feedback_constraints,
            inference_client=self.env.inference_client,
            turn_index=1,
        )
        cards = [card for item in result.decision.final_items if (card := item_to_display_card(item))]
        items = [card.to_dict() for card in cards]
        display = validate_public_display_payload(DisplayResponse(
            session_id=request_id,
            user_id=normalized_sequence["user_id"],
            turn_index=1,
            assistant_message=_public_assistant_message(items),
            items=cards,
            feedback_actions=[],
            ui_state={
                "image_fallback_enabled": True,
                "can_request_more": True,
            },
        ).to_dict())
        return OnlineRecommendationResult(
            request_id=request_id,
            display=display,
            items=items,
            candidate_count=len(result.candidates),
            fallback_used=result.fallback_used,
        )


def _normalize_sequence(user_sequence: dict[str, Any], user_id: str | None) -> dict[str, Any]:
    sequence = dict(user_sequence)
    resolved_user_id = str(user_id or sequence.get("user_id") or f"online-{uuid4()}")
    sequence["user_id"] = resolved_user_id
    for key in ("recent_item_sequence", "recent_positive_item_sequence", "recent_strong_positive_item_sequence"):
        value = sequence.get(key)
        if value is None:
            sequence[key] = []
        elif isinstance(value, list):
            sequence[key] = [str(item) for item in value if item not in (None, "")]
        else:
            raise ValueError(f"user_sequence.{key} must be a list when provided")
    return sequence


def _request_config(config: dict[str, Any], *, top_k: int, candidate_pool_size: int | None) -> dict[str, Any]:
    request_config = dict(config)
    request_config["top_k"] = int(top_k)
    if candidate_pool_size is not None:
        request_config["candidate_pool_size"] = int(candidate_pool_size)
    return request_config


def _public_assistant_message(items: list[dict[str, Any]]) -> str:
    if not items:
        return "暂时没有找到合适的商品，你可以补充更多历史行为或偏好。"
    return "我根据你的历史行为和当前偏好，为你推荐了这些商品。"
