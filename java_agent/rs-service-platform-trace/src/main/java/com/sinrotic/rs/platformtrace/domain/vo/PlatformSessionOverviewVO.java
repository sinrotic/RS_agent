package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record PlatformSessionOverviewVO(
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("account_profile")
        PlatformAccountProfileVO accountProfile,
        @JsonProperty("agent_trace")
        AgentSessionTraceVO agentTrace,
        @JsonProperty("recommend_traces")
        List<RecommendTraceVO> recommendTraces,
        @JsonProperty("interaction_events")
        List<PlatformInteractionEventVO> interactionEvents,
        @JsonProperty("timeline")
        List<PlatformTimelineEventVO> timeline
) {
    public PlatformSessionOverviewVO {
        recommendTraces = recommendTraces == null ? List.of() : List.copyOf(recommendTraces);
        interactionEvents = interactionEvents == null ? List.of() : List.copyOf(interactionEvents);
        timeline = timeline == null ? List.of() : List.copyOf(timeline);
    }
}
