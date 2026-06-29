package com.sinrotic.rs.agent.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record AgentRuntimeSkillUpsertDTO(
        @JsonProperty("description")
        String description,
        @JsonProperty("content")
        String content,
        @JsonProperty("enabled")
        Boolean enabled
) {
}
