package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Homepage recommendation stage-size configuration returned for observability.
 */
public record HomeRecommendConfigVO(
        @JsonProperty("recall_pool_size")
        int recallPoolSize,
        @JsonProperty("coarse_rank_size")
        int coarseRankSize,
        @JsonProperty("fine_rank_size")
        int fineRankSize,
        @JsonProperty("final_return_size")
        int finalReturnSize,
        @JsonProperty("first_screen_display_size")
        int firstScreenDisplaySize
) {
}
