package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;

import java.util.Map;

public record AgentToolUseResult(
        String toolCallId,
        AgentModelStreamEvent event,
        Map<String, Object> metadata,
        Throwable error
) {

    public AgentToolUseResult {
        metadata = metadata == null ? Map.of() : Map.copyOf(metadata);
    }

    public boolean succeeded() {
        return error == null;
    }
}
