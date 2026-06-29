package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record RecommendTraceItemVO(
        @JsonProperty("item_id")
        String itemId,
        @JsonProperty("final_rank")
        int finalRank,
        @JsonProperty("final_score")
        double finalScore,
        @JsonProperty("recall_sources")
        List<String> recallSources,
        String reason
) {
    public RecommendTraceItemVO {
        recallSources = recallSources == null ? List.of() : List.copyOf(recallSources);
    }
}
