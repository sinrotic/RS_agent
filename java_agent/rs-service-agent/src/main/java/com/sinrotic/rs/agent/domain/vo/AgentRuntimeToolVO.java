package com.sinrotic.rs.agent.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Map;

public record AgentRuntimeToolVO(
        @JsonProperty("name")
        String name,
        @JsonProperty("service")
        String service,
        @JsonProperty("description")
        String description,
        @JsonProperty("enabled")
        boolean enabled,
        @JsonProperty("parameters_schema")
        Map<String, Object> parametersSchema
) {
}
