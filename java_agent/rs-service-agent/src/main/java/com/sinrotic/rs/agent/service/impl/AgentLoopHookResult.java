package com.sinrotic.rs.agent.service.impl;

import java.util.Map;

public record AgentLoopHookResult(
        boolean blocked,
        boolean preventContinuation,
        String message,
        Map<String, Object> updatedToolArguments,
        Map<String, Object> additionalContext
) {

    public static AgentLoopHookResult proceed() {
        return new AgentLoopHookResult(false, false, "", Map.of(), Map.of());
    }

    public static AgentLoopHookResult block(String message) {
        return new AgentLoopHookResult(true, false, message == null ? "" : message, Map.of(), Map.of());
    }

    public static AgentLoopHookResult prevent(String message) {
        return new AgentLoopHookResult(false, true, message == null ? "" : message, Map.of(), Map.of());
    }

    public AgentLoopHookResult withUpdatedToolArguments(Map<String, Object> arguments) {
        return new AgentLoopHookResult(
                blocked,
                preventContinuation,
                message,
                arguments == null ? Map.of() : Map.copyOf(arguments),
                additionalContext
        );
    }

    public AgentLoopHookResult withAdditionalContext(Map<String, Object> context) {
        return new AgentLoopHookResult(
                blocked,
                preventContinuation,
                message,
                updatedToolArguments,
                context == null ? Map.of() : Map.copyOf(context)
        );
    }

    public boolean hasUpdatedToolArguments() {
        return !updatedToolArguments.isEmpty();
    }

    public boolean hasAdditionalContext() {
        return !additionalContext.isEmpty();
    }
}
