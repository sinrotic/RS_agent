package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record AgentSessionTraceVO(
        @JsonProperty("session_id")
        String sessionId,
        List<AgentTurnVO> turns
) {
    public AgentSessionTraceVO {
        turns = turns == null ? List.of() : List.copyOf(turns);
    }

    public static AgentSessionTraceVO empty(String sessionId) {
        return new AgentSessionTraceVO(sessionId, List.of());
    }
}
