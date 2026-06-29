package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Internal recommendation response for service-to-service callers.
 */
public record InternalRecommendVO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("profile_user_id")
        String profileUserId,
        List<RecommendItemVO> items,
        @JsonProperty("trace_summary")
        InternalRecommendTraceSummaryVO traceSummary
) {
}
