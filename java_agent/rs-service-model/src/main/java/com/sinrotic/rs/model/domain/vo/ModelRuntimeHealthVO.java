package com.sinrotic.rs.model.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record ModelRuntimeHealthVO(
        @JsonProperty("model_key") String modelKey,
        String status,
        String runtime,
        String endpoint,
        @JsonProperty("last_check_at") String lastCheckAt,
        @JsonProperty("latency_ms") long latencyMs
) {
}
