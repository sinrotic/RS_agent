from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from rs_core.serving.schemas import RecallRequest, RecallResponse, RecommendFromSequenceRequest, RecommendFromSequenceResponse

ONLINE_PUBLIC_TRACE_ALLOWED_FIELDS = {
    "ranker",
    "returned_count",
    "route",
    "source_summary",
    "target_pool_size",
    "path_count",
}
ONLINE_PUBLIC_TRACE_FORBIDDEN_FIELDS = {
    "agent_tool_trace",
    "diagnostics_path",
    "ground_truth",
    "holdout",
    "label_binary",
    "oracle",
    "pool200_eval_labels",
    "pool500_source_lineage",
    "score_trace",
    "shadow_evidence",
    "training_samples",
}
POOL_EVIDENCE_FIELD_BOUNDARY = {
    "pool200": "offline_evaluation_only_not_public_online_trace",
    "pool500": "recall_readiness_or_shadow_evidence_not_ranking_replacement",
    "shadow_evidence": "internal_diagnostics_only_not_public_response",
}


@dataclass(frozen=True)
class RecallTrace:
    target_pool_size: int | None = None
    path_count: int | None = None
    source_summary: str = "engine_fallback"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecallResult:
    request_id: str
    candidate_item_ids: list[str] = field(default_factory=list)
    candidate_count: int = 0
    retrieval_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RankingRequest:
    candidate_item_ids: list[str] = field(default_factory=list)
    return_top_k: int = 20
    ranking_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RankingTrace:
    ranker: str = "stable_input_order"
    returned_count: int = 0
    route: str = "engine_fallback"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RankingResult:
    ranked_item_ids: list[str] = field(default_factory=list)
    ranking_trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecommendationResult:
    request_id: str
    display: dict[str, Any]
    items: list[dict[str, Any]] = field(default_factory=list)
    candidate_count: int = 0
    fallback_used: bool = False
    ranking_trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ONLINE_PUBLIC_TRACE_ALLOWED_FIELDS",
    "ONLINE_PUBLIC_TRACE_FORBIDDEN_FIELDS",
    "POOL_EVIDENCE_FIELD_BOUNDARY",
    "RecommendFromSequenceRequest",
    "RecommendFromSequenceResponse",
    "RecallRequest",
    "RecallResponse",
    "RecallTrace",
    "RecallResult",
    "RankingRequest",
    "RankingTrace",
    "RankingResult",
    "RecommendationResult",
]
