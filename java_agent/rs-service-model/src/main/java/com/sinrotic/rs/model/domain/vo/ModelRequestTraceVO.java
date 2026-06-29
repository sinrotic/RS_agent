package com.sinrotic.rs.model.domain.vo;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record ModelRequestTraceVO(
        @JsonProperty("request_id") String requestId,
        @JsonProperty("model_key") String modelKey,
        @JsonProperty("model_version") String modelVersion,
        String runtime,
        @JsonProperty("latency_ms") long latencyMs,
        String status,
        @JsonProperty("error_code") String errorCode
) {
}
