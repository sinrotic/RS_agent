package com.sinrotic.rs.agent.service.impl;

import java.util.Map;

public record PendingToolCall(
        String toolCallId,
        String toolName,
        Map<String, Object> arguments,
        AgentLoopPhase startedPhase
) {
    public PendingToolCall {
        arguments = arguments == null ? Map.of() : Map.copyOf(arguments);
    }
}
