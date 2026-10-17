package com.sinrotic.rs.agent.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

public record AgentChatVO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("profile_user_id")
        String profileUserId,
        @JsonProperty("card_set_id")
        String cardSetId,
        @JsonProperty("turn_index")
        int turnIndex,
        @JsonProperty("assistant_message")
        String assistantMessage,
        @JsonProperty("recommended_items")
        List<AgentRecommendedItemVO> recommendedItems,
        @JsonProperty("tool_calls")
        List<AgentToolCallVO> toolCalls,
        @JsonProperty("answer_blocks")
        List<Map<String, Object>> answerBlocks,
        @JsonProperty("degradation_reasons") List<String> degradationReasons
) {
    public AgentChatVO {
        toolCalls = toolCalls == null ? List.of() : List.copyOf(toolCalls);
        answerBlocks = answerBlocks == null ? List.of() : List.copyOf(answerBlocks);
        degradationReasons = degradationReasons == null ? List.of() : List.copyOf(degradationReasons);
    }
    public AgentChatVO(String requestId, String sessionId, String profileUserId, String cardSetId,
            int turnIndex, String assistantMessage, List<AgentRecommendedItemVO> recommendedItems,
            List<AgentToolCallVO> toolCalls, List<Map<String, Object>> answerBlocks) {
        this(requestId, sessionId, profileUserId, cardSetId, turnIndex, assistantMessage, recommendedItems,
                toolCalls, answerBlocks, List.of());
    }
    public AgentChatVO(String requestId, String sessionId, String profileUserId, String cardSetId,
                       int turnIndex, String assistantMessage, List<AgentRecommendedItemVO> recommendedItems,
                       List<AgentToolCallVO> toolCalls) {
        this(requestId, sessionId, profileUserId, cardSetId, turnIndex, assistantMessage,
                recommendedItems, toolCalls, List.of());
    }
    public AgentChatVO(
            String requestId,
            String sessionId,
            String profileUserId,
            int turnIndex,
            String assistantMessage,
            List<AgentRecommendedItemVO> recommendedItems,
            List<AgentToolCallVO> toolCalls
    ) {
        this(requestId, sessionId, profileUserId, "", turnIndex, assistantMessage, recommendedItems, toolCalls, List.of());
    }
}
