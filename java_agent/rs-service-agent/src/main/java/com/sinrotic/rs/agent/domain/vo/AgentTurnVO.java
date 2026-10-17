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
        List<String> recommendedItemIds,
        @JsonProperty("answer_blocks") List<java.util.Map<String, Object>> answerBlocks,
        @JsonProperty("finish_reason") String finishReason,
        @JsonProperty("card_set_id") String cardSetId,
        @JsonProperty("degradation_reasons") List<String> degradationReasons
) {
    public AgentTurnVO(String requestId, String userMessage, String assistantMessage,
            List<AgentToolCallVO> toolCalls, List<String> recommendedItemIds,
            List<java.util.Map<String, Object>> answerBlocks, String finishReason, String cardSetId) {
        this(requestId, userMessage, assistantMessage, toolCalls, recommendedItemIds, answerBlocks, finishReason, cardSetId, List.of());
    }
    public AgentTurnVO(String requestId, String userMessage, String assistantMessage,
            List<AgentToolCallVO> toolCalls, List<String> recommendedItemIds) {
        this(requestId, userMessage, assistantMessage, toolCalls, recommendedItemIds, List.of(), "FINAL_ANSWER", "");
    }
}
