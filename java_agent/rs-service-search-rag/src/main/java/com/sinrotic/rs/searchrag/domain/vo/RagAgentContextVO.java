package com.sinrotic.rs.searchrag.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Compact context for the Agent final answer step.
 */
public record RagAgentContextVO(
        String summary,
        @JsonProperty("should_ask_clarifying_question")
        boolean shouldAskClarifyingQuestion
) {
}
