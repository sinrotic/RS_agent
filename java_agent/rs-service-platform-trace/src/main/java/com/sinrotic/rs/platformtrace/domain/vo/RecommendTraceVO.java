package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

public record RecommendTraceVO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("profile_user_id")
        String profileUserId,
        String scene,
        @JsonProperty("stage_counts")
        Map<String, Integer> stageCounts,
        @JsonProperty("source_distribution")
        Map<String, Integer> sourceDistribution,
        List<RecommendTraceItemVO> items
) {
    public RecommendTraceVO {
        stageCounts = stageCounts == null ? Map.of() : Map.copyOf(stageCounts);
        sourceDistribution = sourceDistribution == null ? Map.of() : Map.copyOf(sourceDistribution);
        items = items == null ? List.of() : List.copyOf(items);
    }

    public static RecommendTraceVO empty(String requestId) {
        return new RecommendTraceVO(requestId, "", "", "", Map.of(), Map.of(), List.of());
    }
}
