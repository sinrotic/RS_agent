package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Homepage recommendation response.
 */
public record HomeRecommendVO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("session_id")
        String sessionId,
        String scene,
        @JsonProperty("profile_user_id")
        String profileUserId,
        List<RecommendItemVO> items,
        @JsonProperty("has_more")
        boolean hasMore,
        @JsonProperty("next_cursor")
        String nextCursor,
        HomeRecommendConfigVO config,
        @JsonProperty("preference_version")
        long preferenceVersion,
        @JsonProperty("applied_feedback_event_ids")
        List<String> appliedFeedbackEventIds,
        @JsonProperty("recommendation_mode") String recommendationMode,
        @JsonProperty("degradation_reasons") List<String> degradationReasons
) {
    public HomeRecommendVO(String requestId, String sessionId, String scene, String profileUserId,
            List<RecommendItemVO> items, boolean hasMore, String nextCursor, HomeRecommendConfigVO config,
            long preferenceVersion, List<String> appliedFeedbackEventIds) {
        this(requestId, sessionId, scene, profileUserId, items, hasMore, nextCursor, config,
                preferenceVersion, appliedFeedbackEventIds, "catalog_cold_start", List.of());
    }

    public HomeRecommendVO(
            String requestId,
            String sessionId,
            String scene,
            String profileUserId,
            List<RecommendItemVO> items,
            boolean hasMore,
            String nextCursor,
            HomeRecommendConfigVO config
    ) {
        this(requestId, sessionId, scene, profileUserId, items, hasMore, nextCursor, config, 0L, List.of());
    }

    public HomeRecommendVO {
        appliedFeedbackEventIds = appliedFeedbackEventIds == null ? List.of() : List.copyOf(appliedFeedbackEventIds);
        degradationReasons = degradationReasons == null ? List.of() : List.copyOf(degradationReasons);
    }
}
