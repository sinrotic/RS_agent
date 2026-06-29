package com.sinrotic.rs.model.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

public record ModelRankSignalsVO(
        @JsonProperty("request_id") String requestId,
        @JsonProperty("model_key") String modelKey,
        @JsonProperty("model_version") String modelVersion,
        String runtime,
        @JsonProperty("latency_ms") long latencyMs,
        List<RankSignalVO> signals,
        Map<String, Object> diagnostics
) {
}
