package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record AgentRunRelatedTraceVO(
        @JsonProperty("agent_turn_count")
        Integer agentTurnCount,
        @JsonProperty("recommend_request_ids")
        List<String> recommendRequestIds,
        @JsonProperty("interaction_event_count")
        Integer interactionEventCount
) {
    public AgentRunRelatedTraceVO {
        agentTurnCount = agentTurnCount == null ? 0 : agentTurnCount;
        recommendRequestIds = recommendRequestIds == null ? List.of() : List.copyOf(recommendRequestIds);
        interactionEventCount = interactionEventCount == null ? 0 : interactionEventCount;
    }

    public static AgentRunRelatedTraceVO empty() {
        return new AgentRunRelatedTraceVO(0, List.of(), 0);
    }
}
