from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RecallCandidate:
    item_id: str
    source: str
    score: float = 0.0
    category: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MergedCandidate:
    item_id: str
    sources: list[str]
    source_scores: dict[str, float]
    category: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RankingResult:
    user_id: str
    items: list[dict[str, Any]]
    fallback_used: bool = False


@dataclass
class AgentDecision:
    user_id: str
    strategy_name: str
    trigger_reason: str
    agent_explanation: str
    risk_flags: list[str]
    limitations: list[str]
    final_items: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvaluationSummary:
    evaluation_mode: str
    users_total: int
    users_with_holdout: int
    users_evaluated: int
    hit_rate_denominator: str
    candidate_count_avg: float
    recall_source_coverage: dict[str, int]
    topk_source_coverage: dict[str, int]
    source_diagnostics: dict[str, int]
    candidate_hit_rate_at_pool: float
    candidate_hit_users: int
    candidate_hit_source_coverage: dict[str, int]
    candidate_hit_rank_min: int | None
    candidate_hit_rank_avg: float | None
    candidate_hit_rank_p50: float | None
    candidate_hit_missed_topk_users: int
    ranked_hit_users: int
    fallback_rate: float
    hit_rate_at_k: float
    popular_only_hit_rate_at_k: float
    itemcf_only_hit_rate_at_k: float
    hybrid_hit_rate_at_k: float
    hybrid_no_itemcf_hit_rate_at_k: float
    category_diversity_avg: float
    sample_limitations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
