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
    empty_candidate_users: int
    empty_candidate_rate: float
    user_candidate_coverage_rate: float
    candidate_count_min: int
    candidate_count_p50: float
    candidate_count_p90: float
    candidate_count_max: int
    candidate_hit_rate_at_cutoffs: dict[str, float]
    candidate_recall_at_cutoffs: dict[str, float]
    catalog_candidate_coverage_count: int
    catalog_candidate_coverage_rate: float | None
    source_user_coverage: dict[str, int]
    source_item_coverage: dict[str, int]
    source_marginal_candidate_hit_users: dict[str, int]
    source_marginal_candidate_hit_rate: dict[str, float]
    recall_source_coverage: dict[str, int]
    topk_source_coverage: dict[str, int]
    source_diagnostics: dict[str, int]
    method_card_diagnostics: dict[str, Any]
    candidate_hit_rate_at_pool: float
    candidate_hit_users: int
    candidate_hit_source_coverage: dict[str, int]
    candidate_hit_rank_min: int | None
    candidate_hit_rank_avg: float | None
    candidate_hit_rank_p50: float | None
    candidate_hit_rank_p90: float | None
    candidate_hit_missed_topk_users: int
    ranked_hit_users: int
    fallback_rate: float
    recall_at_k: float
    recall_at_pool: float
    ndcg_at_k: float
    mrr_at_k: float
    map_at_k: float
    hit_rate_at_k: float
    per_source_candidate_contribution: dict[str, int]
    per_source_topk_contribution: dict[str, int]
    source_overlap: dict[str, Any]
    popular_only_hit_rate_at_k: float
    itemcf_only_hit_rate_at_k: float
    hybrid_hit_rate_at_k: float
    hybrid_no_itemcf_hit_rate_at_k: float
    category_diversity_avg: float
    sample_limitations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
