package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record AgentTraceEventsVO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("events")
        List<AgentTraceEventVO> events
) {
    public AgentTraceEventsVO {
        events = events == null ? List.of() : List.copyOf(events);
    }
}
