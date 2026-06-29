package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Trace detail for one final recommendation item.
 */
public record RecommendTraceItemVO(
        @JsonProperty("item_id")
        String itemId,
        @JsonProperty("final_rank")
        int finalRank,
        @JsonProperty("final_score")
        double finalScore,
        @JsonProperty("recall_sources")
        List<String> recallSources,
        @JsonProperty("coarse_rank")
        Integer coarseRank,
        @JsonProperty("fine_rank")
        Integer fineRank,
        String reason
) {
}
