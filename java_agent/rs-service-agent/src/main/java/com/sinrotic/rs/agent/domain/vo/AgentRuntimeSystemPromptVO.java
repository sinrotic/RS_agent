package com.sinrotic.rs.agent.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record AgentRuntimeSystemPromptVO(
        @JsonProperty("name")
        String name,
        @JsonProperty("content")
        String content
) {
}
