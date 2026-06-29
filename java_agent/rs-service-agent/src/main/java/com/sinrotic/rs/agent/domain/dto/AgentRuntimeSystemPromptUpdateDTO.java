package com.sinrotic.rs.agent.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record AgentRuntimeSystemPromptUpdateDTO(
        @JsonProperty("name")
        String name,
        @JsonProperty("content")
        String content
) {
}
