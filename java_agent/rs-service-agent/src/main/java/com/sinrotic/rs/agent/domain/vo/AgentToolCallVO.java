package com.sinrotic.rs.agent.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Map;

public record AgentToolCallVO(
        @JsonProperty("tool_call_id")
        String toolCallId,
        @JsonProperty("tool_name")
        String toolName,
        @JsonProperty("service")
        String service,
        @JsonProperty("status")
        String status,
        @JsonProperty("metadata")
        Map<String, Object> metadata
) {
    public AgentToolCallVO(String toolName, String service, String status, Map<String, Object> metadata) {
        this("", toolName, service, status, metadata);
    }
}
