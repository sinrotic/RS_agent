package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.Map;

public record AgentRunEventVO(
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
        @JsonProperty("error_code")
        String errorCode,
        @JsonProperty("error_message")
        String errorMessage,
        @JsonProperty("input_summary")
        String inputSummary,
        @JsonProperty("output_summary")
        String outputSummary,
        Map<String, Object> data,
        @JsonProperty("created_at")
        Instant createdAt
) {
    public AgentRunEventVO {
        eventId = eventId == null ? "" : eventId;
        sessionId = sessionId == null ? "" : sessionId;
        requestId = requestId == null ? "" : requestId;
        eventType = eventType == null ? "" : eventType;
        phase = phase == null ? "" : phase;
        status = status == null ? "" : status;
        toolCallId = toolCallId == null ? "" : toolCallId;
        toolName = toolName == null ? "" : toolName;
        agentName = agentName == null ? "" : agentName;
        modelProvider = modelProvider == null ? "" : modelProvider;
        modelName = modelName == null ? "" : modelName;
        errorCode = errorCode == null ? "" : errorCode;
        errorMessage = errorMessage == null ? "" : errorMessage;
        inputSummary = inputSummary == null ? "" : inputSummary;
        outputSummary = outputSummary == null ? "" : outputSummary;
        data = data == null ? Map.of() : Map.copyOf(data);
        createdAt = createdAt == null ? Instant.now() : createdAt;
    }
}
