package com.sinrotic.rs.model.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Map;

public record ModelChatVO(
        @JsonProperty("request_id") String requestId,
        @JsonProperty("model_key") String modelKey,
        @JsonProperty("model_version") String modelVersion,
        String runtime,
        @JsonProperty("latency_ms") long latencyMs,
        ModelMessageVO message,
        Map<String, Object> usage
) {
}
