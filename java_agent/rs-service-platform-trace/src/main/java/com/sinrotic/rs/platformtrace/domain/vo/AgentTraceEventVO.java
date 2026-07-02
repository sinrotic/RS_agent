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
        String phase,
        String status,
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
        @JsonProperty("prompt_tokens")
        Integer promptTokens,
        @JsonProperty("completion_tokens")
        Integer completionTokens,
        @JsonProperty("total_tokens")
        Integer totalTokens,
        @JsonProperty("cache_read_input_tokens")
        Long cacheReadInputTokens,
        @JsonProperty("cache_write_input_tokens")
        Long cacheWriteInputTokens,
        @JsonProperty("error_code")
        String errorCode,
        @JsonProperty("error_message")
        String errorMessage,
        @JsonProperty("input_summary")
        String inputSummary,
        @JsonProperty("output_summary")
        String outputSummary,
        @JsonProperty("data")
        Map<String, Object> data,
        @JsonProperty("created_at")
        Instant createdAt
) {
    public AgentTraceEventVO(
            String eventId,
            String sessionId,
            String requestId,
            String eventType,
            String toolCallId,
            String toolName,
            String agentName,
            String modelProvider,
            String modelName,
            Long latencyMs,
            Map<String, Object> data,
            Instant createdAt
    ) {
        this(eventId, sessionId, requestId, eventType, null, null, toolCallId, toolName, agentName, modelProvider, modelName,
                latencyMs, null, null, null, null, null, null, null, null, null, data, createdAt);
    }

    public AgentTraceEventVO(
            String eventId,
            String sessionId,
            String requestId,
            String eventType,
            String toolCallId,
            String toolName,
            String agentName,
            String modelProvider,
            String modelName,
            Long latencyMs,
            Integer promptTokens,
            Integer completionTokens,
            Integer totalTokens,
            Long cacheReadInputTokens,
            Long cacheWriteInputTokens,
            Map<String, Object> data,
            Instant createdAt
    ) {
        this(eventId, sessionId, requestId, eventType, null, null, toolCallId, toolName, agentName, modelProvider, modelName,
                latencyMs, promptTokens, completionTokens, totalTokens, cacheReadInputTokens, cacheWriteInputTokens,
                null, null, null, null, data, createdAt);
    }

    public AgentTraceEventVO(
            String eventId,
            String sessionId,
            String requestId,
            String eventType,
            String phase,
            String status,
            String toolCallId,
            String toolName,
            String agentName,
            String modelProvider,
            String modelName,
            Long latencyMs,
            Integer promptTokens,
            Integer completionTokens,
            Integer totalTokens,
            String errorCode,
            String errorMessage,
            String inputSummary,
            String outputSummary,
            Map<?, ?> data,
            Instant createdAt
    ) {
        this(eventId, sessionId, requestId, eventType, phase, status, toolCallId, toolName, agentName, modelProvider, modelName,
                latencyMs, promptTokens, completionTokens, totalTokens, null, null, errorCode, errorMessage,
                inputSummary, outputSummary, copyData(data), createdAt);
    }

    public AgentTraceEventVO {
        data = data == null ? Map.of() : Map.copyOf(data);
        createdAt = createdAt == null ? Instant.now() : createdAt;
    }

    private static Map<String, Object> copyData(Map<?, ?> data) {
        if (data == null || data.isEmpty()) {
            return Map.of();
        }
        java.util.LinkedHashMap<String, Object> copy = new java.util.LinkedHashMap<>();
        data.forEach((key, value) -> copy.put(String.valueOf(key), value));
        return Map.copyOf(copy);
    }
}
