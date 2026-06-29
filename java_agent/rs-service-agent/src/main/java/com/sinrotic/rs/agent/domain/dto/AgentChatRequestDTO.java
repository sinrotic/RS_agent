package com.sinrotic.rs.agent.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Map;

public record AgentChatRequestDTO(
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("profile_user_id")
        String profileUserId,
        @JsonProperty("user_message")
        String userMessage,
        @JsonProperty("limit")
        Integer limit,
        @JsonProperty("context")
        Map<String, Object> context
) {

    public int resolvedLimit() {
        if (limit == null || limit <= 0) {
            return 5;
        }
        return limit;
    }

    public Map<String, Object> resolvedContext() {
        if (context == null) {
            return Map.of();
        }
        return context;
    }
}
