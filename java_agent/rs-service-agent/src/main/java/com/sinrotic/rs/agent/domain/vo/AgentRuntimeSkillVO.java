package com.sinrotic.rs.agent.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record AgentRuntimeSkillVO(
        @JsonProperty("name")
        String name,
        @JsonProperty("description")
        String description,
        @JsonProperty("source")
        String source,
        @JsonProperty("enabled")
        boolean enabled,
        @JsonProperty("content")
        String content
) {
}
