package com.sinrotic.rs.agent.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record AgentInterruptVO(
        @JsonProperty("request_id")
        String requestId,
        boolean interrupted,
        String reason
) {
}
