package com.sinrotic.rs.agent.service.impl;

import java.util.Map;

public record AgentModelStreamEvent(
        String type,
        String delta,
        String toolCallId,
        String toolName,
        Map<String, Object> arguments
) {

    public static AgentModelStreamEvent token(String delta) {
        return new AgentModelStreamEvent("token", delta, "", "", Map.of());
    }

    public static AgentModelStreamEvent toolUse(String toolName, Map<String, Object> arguments) {
        return toolUse("", toolName, arguments);
    }

    public static AgentModelStreamEvent toolUse(String toolCallId, String toolName, Map<String, Object> arguments) {
        return new AgentModelStreamEvent(
                "tool_use",
                "",
                toolCallId == null ? "" : toolCallId,
                toolName,
                arguments == null ? Map.of() : arguments
        );
    }

    public static AgentModelStreamEvent done() {
        return new AgentModelStreamEvent("done", "", "", "", Map.of());
    }

    public static AgentModelStreamEvent usage(Map<String, Object> usage) {
        return new AgentModelStreamEvent("usage", "", "", "", usage == null ? Map.of() : Map.copyOf(usage));
    }

    public boolean isToken() {
        return "token".equals(type);
    }

    public boolean isToolUse() {
        return "tool_use".equals(type);
    }

    public boolean isDone() {
        return "done".equals(type);
    }

    public boolean isUsage() {
        return "usage".equals(type);
    }
}
