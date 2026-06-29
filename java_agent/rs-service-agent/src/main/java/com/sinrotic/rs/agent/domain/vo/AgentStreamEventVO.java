package com.sinrotic.rs.agent.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Map;

public record AgentStreamEventVO(
        @JsonProperty("event")
        String event,
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("data")
        Map<String, Object> data
) {
}
