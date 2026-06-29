package com.sinrotic.rs.agent.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record AgentChatVO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("profile_user_id")
        String profileUserId,
        @JsonProperty("assistant_message")
        String assistantMessage,
        @JsonProperty("recommended_items")
        List<AgentRecommendedItemVO> recommendedItems,
        @JsonProperty("tool_calls")
        List<AgentToolCallVO> toolCalls
) {
}
