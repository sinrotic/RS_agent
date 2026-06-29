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
        HomeRecommendConfigVO config
) {
}
