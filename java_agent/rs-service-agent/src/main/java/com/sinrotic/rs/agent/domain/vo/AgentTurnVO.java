package com.sinrotic.rs.agent.domain.vo;

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
        List<AgentToolCallVO> toolCalls,
        @JsonProperty("recommended_item_ids")
        List<String> recommendedItemIds
) {
}
