package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record AgentRunMonitorVO(
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("request_id")
        String requestId,
        String status,
        AgentRunSummaryVO summary,
        List<AgentRunPhaseVO> phases,
        List<AgentRunEventVO> events,
        @JsonProperty("quality_signals")
        List<String> qualitySignals,
        @JsonProperty("related_traces")
        AgentRunRelatedTraceVO relatedTraces
) {
    public AgentRunMonitorVO {
        sessionId = sessionId == null ? "" : sessionId;
        requestId = requestId == null ? "" : requestId;
        status = status == null ? "" : status;
        summary = summary == null ? AgentRunSummaryVO.empty() : summary;
        phases = phases == null ? List.of() : List.copyOf(phases);
        events = events == null ? List.of() : List.copyOf(events);
        qualitySignals = qualitySignals == null ? List.of() : List.copyOf(qualitySignals);
        relatedTraces = relatedTraces == null ? AgentRunRelatedTraceVO.empty() : relatedTraces;
    }

    public static AgentRunMonitorVO empty(String sessionId, String requestId) {
        return new AgentRunMonitorVO(
                sessionId,
                requestId,
                "partial",
                AgentRunSummaryVO.empty(),
                List.of(),
                List.of(),
                List.of("partial_trace"),
                AgentRunRelatedTraceVO.empty()
        );
    }
}
