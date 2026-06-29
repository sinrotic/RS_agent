package com.sinrotic.rs.agent.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record AgentSessionTraceVO(
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("turns")
        List<AgentTurnVO> turns
) {
}
