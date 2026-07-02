package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record AgentRunPhaseVO(
        String phase,
        String status,
        @JsonProperty("event_count")
        Integer eventCount,
        @JsonProperty("latency_ms")
        Long latencyMs,
        @JsonProperty("total_tokens")
        Integer totalTokens
) {
    public AgentRunPhaseVO {
        phase = phase == null ? "" : phase;
        status = status == null ? "" : status;
        eventCount = eventCount == null ? 0 : eventCount;
        latencyMs = latencyMs == null ? 0L : latencyMs;
        totalTokens = totalTokens == null ? 0 : totalTokens;
    }
}
