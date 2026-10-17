package com.sinrotic.rs.agent.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Map;

/** User-visible history deliberately excludes runtime tool metadata. */
public record AgentPublicHistoryVO(@JsonProperty("session_id") String sessionId, List<Turn> turns) {
    public record Turn(@JsonProperty("request_id") String requestId,
            @JsonProperty("turn_index") int turnIndex,
            @JsonProperty("user_message") String userMessage,
            @JsonProperty("assistant_message") String assistantMessage,
            @JsonProperty("recommended_item_ids") List<String> recommendedItemIds,
            @JsonProperty("answer_blocks") List<Map<String, Object>> answerBlocks,
            @JsonProperty("finish_reason") String finishReason,
            @JsonProperty("card_set_id") String cardSetId,
            @JsonProperty("degradation_reasons") List<String> degradationReasons) {}
}
