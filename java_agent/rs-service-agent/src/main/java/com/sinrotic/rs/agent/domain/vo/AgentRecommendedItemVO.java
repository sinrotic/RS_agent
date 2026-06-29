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
        String reason
) {
}
