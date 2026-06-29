package com.sinrotic.rs.searchrag.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Recall provider execution summary.
 */
public record RagPipelineProviderStatusVO(
        String provider,
        String status,
        @JsonProperty("hit_count")
        int hitCount,
        @JsonProperty("latency_ms")
        long latencyMs
) {
}
