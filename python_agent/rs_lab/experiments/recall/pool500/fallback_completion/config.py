from __future__ import annotations

from dataclasses import dataclass, field

from rs_lab.experiments.recall.pool500.governance.fallback_completion_contract import (
    FALLBACK_SOURCE_LADDER,
    FallbackCompletionConfig,
    FallbackSource,
)

FALLBACK_STAGE = "pool500_universal_fallback"
FALLBACK_SOURCE_TO_CANONICAL_SOURCE = {
    FallbackSource.SEED_CATEGORY_SIBLING.value: "category",
    FallbackSource.SEED_METADATA_NEIGHBOR.value: "co_visit_fallback_repair",
    FallbackSource.SEED_SEMANTIC_TOKEN.value: "semantic_title_category_expansion",
    FallbackSource.CATEGORY_POPULAR.value: "category",
    FallbackSource.SESSION_OR_CONTEXT_POPULAR.value: "popular",
    FallbackSource.GLOBAL_DIVERSITY_POPULAR.value: "popular",
}


@dataclass
class Pool500FallbackCompletionConfig:
    contract: FallbackCompletionConfig = field(default_factory=FallbackCompletionConfig)
    stage: str = FALLBACK_STAGE
    fallback_reason: str = "low_history_completion"
    source_to_canonical_source: dict[str, str] = field(default_factory=lambda: dict(FALLBACK_SOURCE_TO_CANONICAL_SOURCE))
    source_ladder: tuple[FallbackSource, ...] = FALLBACK_SOURCE_LADDER
    forbidden_data_markers: tuple[str, ...] = ("holdout", "valid", "test", "lopo", "leave_one_positive_out", "clean_10000")
    max_index_bucket_size: int = 1500
    semantic_token_limit_per_seed: int = 12
    global_popular_category_diversity_buckets: int = 8

    @property
    def target_candidate_count(self) -> int:
        return self.contract.target_candidate_count

    @property
    def normal_threshold(self) -> int:
        return self.contract.normal_threshold

    @property
    def source_caps(self) -> dict[str, int]:
        return self.contract.source_caps
