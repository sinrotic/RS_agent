package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

/**
 * Full trace for one recommendation request.
 */
public record RecommendTraceVO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("profile_user_id")
        String profileUserId,
        String scene,
        Map<String, Integer> config,
        @JsonProperty("stage_counts")
        Map<String, Integer> stageCounts,
        @JsonProperty("source_distribution")
        Map<String, Integer> sourceDistribution,
        List<RecommendTraceItemVO> items
) {
}
