package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.Map;

public record AgentTraceEventVO(
        @JsonProperty("event_id")
        String eventId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("event_type")
        String eventType,
        @JsonProperty("tool_call_id")
        String toolCallId,
        @JsonProperty("tool_name")
        String toolName,
        @JsonProperty("agent_name")
        String agentName,
        @JsonProperty("model_provider")
        String modelProvider,
        @JsonProperty("model_name")
        String modelName,
        @JsonProperty("latency_ms")
        Long latencyMs,
        @JsonProperty("data")
        Map<String, Object> data,
        @JsonProperty("created_at")
        Instant createdAt
) {
    public AgentTraceEventVO {
        data = data == null ? Map.of() : Map.copyOf(data);
        createdAt = createdAt == null ? Instant.now() : createdAt;
    }
}
