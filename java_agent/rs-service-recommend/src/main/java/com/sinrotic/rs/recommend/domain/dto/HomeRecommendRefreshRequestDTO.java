package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Request body for homepage pull-to-refresh or pagination refresh.
 */
public record HomeRecommendRefreshRequestDTO(
        @JsonProperty("session_id")
        String sessionId,
        String scene,
        @JsonProperty("page_size")
        Integer pageSize,
        @JsonProperty("refresh_token")
        String refreshToken,
        Boolean debug
) {

    public HomeRecommendRequestDTO toHomeRecommendRequest() {
        return new HomeRecommendRequestDTO(
                sessionId,
                scene,
                pageSize,
                catalogCursor(),
                debug
        ).withDefaults();
    }

    private String catalogCursor() {
        if (refreshToken == null || refreshToken.isBlank()) {
            return "";
        }
        return switch (refreshToken) {
            case "rerecall_pool500", "rerank_existing", "feedback-smoke" -> "";
            default -> refreshToken;
        };
    }
}
