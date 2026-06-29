from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from rs_core.data.clients import ArtifactClient, CandidatePoolClient, FeatureClient
from rs_core.online.contracts import RankingRequest, RankingResult, RankingTrace, RecommendationResult
from rs_core.online.ranking.cold_deepfm import rank_with_cold_deepfm_shadow_contract
from rs_core.online.recall import recall_from_sequence_contract
from rs_core.serving.schemas import RecallRequest, RecommendFromSequenceRequest


class OnlineRecommenderLike(Protocol):
    def recommend(self, user_sequence: dict[str, Any], **kwargs: Any) -> Any: ...
    def recall(self, request: dict[str, Any]) -> Any: ...
    def readiness(self) -> dict[str, Any]: ...


@dataclass
class OnlineRecommendationEngine:
    """Online recommendation boundary: recall + ranking + runtime; no RAG/dialogue ownership."""

    recommender: OnlineRecommenderLike | None = None
    candidate_pool_client: CandidatePoolClient = field(default_factory=CandidatePoolClient)
    feature_client: FeatureClient = field(default_factory=FeatureClient)
    artifact_client: ArtifactClient = field(default_factory=ArtifactClient)

    def ready(self) -> dict[str, Any]:
        dependencies = {
            "candidate_pool_client": type(self.candidate_pool_client).__name__,
            "feature_client": type(self.feature_client).__name__,
            "artifact_client": type(self.artifact_client).__name__,
        }
        if self.recommender is None:
            return {
                "status": "degraded",
                "engine": "OnlineRecommendationEngine",
                "reason": "no_recommender_bound",
                "dependencies": dependencies,
            }
        readiness = self.recommender.readiness()
        readiness.setdefault("dependencies", dependencies)
        return readiness

    def recommend(self, request: RecommendFromSequenceRequest | dict[str, Any]) -> dict[str, Any]:
        payload = request.model_dump() if hasattr(request, "model_dump") else dict(request)
        if self.recommender is None:
            return RecommendationResult(
                request_id=str(uuid4()),
                display={"assistant_message": "online engine is available without a bound recommender", "items": []},
                items=[],
                candidate_count=0,
                fallback_used=True,
                ranking_trace={"route": "unbound_fallback"},
            ).to_dict()
        result = self.recommender.recommend(
            payload.get("user_sequence") or {},
            user_id=payload.get("user_id"),
            feedback_text=payload.get("feedback_text"),
            top_k=payload.get("top_k", 5),
            candidate_pool_size=payload.get("candidate_pool_size"),
            complete_pool500=payload.get("complete_pool500", False),
        )
        if hasattr(result, "to_dict"):
            return result.to_dict()
        if hasattr(result, "__dict__"):
            return dict(result.__dict__)
        return dict(result)

    def recall(self, request: RecallRequest | dict[str, Any]) -> dict[str, Any]:
        recall_request = request if isinstance(request, RecallRequest) else RecallRequest(**dict(request))
        payload = recall_request.model_dump()
        if self.recommender is not None and hasattr(self.recommender, "recall"):
            result = self.recommender.recall(payload)  # type: ignore[attr-defined]
            return result.to_dict() if hasattr(result, "to_dict") else dict(result)
        return recall_from_sequence_contract(recall_request, candidate_pool_client=self.candidate_pool_client).to_dict()

    def rank(self, request: RankingRequest | dict[str, Any]) -> dict[str, Any]:
        ranking_request = request if isinstance(request, RankingRequest) else RankingRequest(**dict(request))
        if _cold_deepfm_shadow_enabled(ranking_request.ranking_context):
            return rank_with_cold_deepfm_shadow_contract(ranking_request, artifact_client=self.artifact_client).to_dict()
        top_k = max(1, int(ranking_request.return_top_k or 20))
        ranked = list(dict.fromkeys(str(item) for item in ranking_request.candidate_item_ids if item))[:top_k]
        return RankingResult(
            ranked_item_ids=ranked,
            ranking_trace=RankingTrace(returned_count=len(ranked)).to_dict(),
        ).to_dict()


def _cold_deepfm_shadow_enabled(ranking_context: dict[str, Any]) -> bool:
    shadow = ranking_context.get("cold_deepfm_shadow") if isinstance(ranking_context, dict) else None
    return isinstance(shadow, dict) and bool(shadow.get("enabled"))


__all__ = ["OnlineRecommendationEngine", "OnlineRecommenderLike"]
