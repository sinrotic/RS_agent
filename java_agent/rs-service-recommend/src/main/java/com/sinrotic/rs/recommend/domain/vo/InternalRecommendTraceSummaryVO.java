package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Stage count summary for internal recommendation observability.
 */
public record InternalRecommendTraceSummaryVO(
        @JsonProperty("recall_count")
        int recallCount,
        @JsonProperty("coarse_rank_count")
        int coarseRankCount,
        @JsonProperty("fine_rank_count")
        int fineRankCount,
        @JsonProperty("final_count")
        int finalCount
) {
}
