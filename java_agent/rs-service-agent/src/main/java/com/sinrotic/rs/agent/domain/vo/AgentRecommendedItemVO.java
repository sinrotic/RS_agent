package com.sinrotic.rs.agent.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record AgentRecommendedItemVO(
        @JsonProperty("item_id")
        String itemId,
        @JsonProperty("title")
        String title,
        @JsonProperty("category")
        String category,
        @JsonProperty("score")
        double score,
        @JsonProperty("reason")
        String reason,
        @JsonProperty("card_set_id")
        String cardSetId
) {
    public AgentRecommendedItemVO(String itemId, String title, String category, double score, String reason) {
        this(itemId, title, category, score, reason, "");
    }
}
