package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record AgentTurnVO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("user_message")
        String userMessage,
        @JsonProperty("assistant_message")
        String assistantMessage,
        @JsonProperty("tool_calls")
        List<String> toolCalls,
        @JsonProperty("recommended_item_ids")
        List<String> recommendedItemIds
) {
    public AgentTurnVO {
        toolCalls = toolCalls == null ? List.of() : List.copyOf(toolCalls);
        recommendedItemIds = recommendedItemIds == null ? List.of() : List.copyOf(recommendedItemIds);
    }
}
