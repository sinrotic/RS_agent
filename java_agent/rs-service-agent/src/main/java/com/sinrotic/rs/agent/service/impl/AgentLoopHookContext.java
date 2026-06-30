package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.AgentLoopHookDispatcher;

import java.util.Map;

public record AgentLoopHookContext(
        String eventName,
        String requestId,
        String agentName,
        int loopIndex,
        AgentChatRequestDTO request,
        String toolCallId,
        String toolName,
        Map<String, Object> toolArguments,
        Map<String, Object> toolResult,
        Map<String, Object> metadata,
        String assistantMessage,
        String errorMessage
) {

    public AgentLoopHookResult dispatch(AgentLoopHookDispatcher dispatcher) {
        return dispatcher.dispatch(this);
    }

    public static AgentLoopHookContext of(
            String eventName,
            String requestId,
            AgentProfile profile,
            int loopIndex,
            AgentChatRequestDTO request
    ) {
        return new AgentLoopHookContext(
                eventName,
                requestId,
                profile.name(),
                loopIndex,
                request,
                "",
                "",
                Map.of(),
                Map.of(),
                Map.of(),
                "",
                ""
        );
    }

    public AgentLoopHookContext withTool(
            String toolCallId,
            String toolName,
            Map<String, Object> toolArguments
    ) {
        return new AgentLoopHookContext(
                eventName,
                requestId,
                agentName,
                loopIndex,
                request,
                toolCallId,
                toolName,
                toolArguments == null ? Map.of() : toolArguments,
                toolResult,
                metadata,
                assistantMessage,
                errorMessage
        );
    }

    public AgentLoopHookContext withToolResult(Map<String, Object> toolResult) {
        return new AgentLoopHookContext(
                eventName,
                requestId,
                agentName,
                loopIndex,
                request,
                toolCallId,
                toolName,
                toolArguments,
                toolResult == null ? Map.of() : toolResult,
                metadata,
                assistantMessage,
                errorMessage
        );
    }

    public AgentLoopHookContext withMetadata(Map<String, Object> metadata) {
        return new AgentLoopHookContext(
                eventName,
                requestId,
                agentName,
                loopIndex,
                request,
                toolCallId,
                toolName,
                toolArguments,
                toolResult,
                metadata == null ? Map.of() : metadata,
                assistantMessage,
                errorMessage
        );
    }

    public AgentLoopHookContext withAssistantMessage(String assistantMessage) {
        return new AgentLoopHookContext(
                eventName,
                requestId,
                agentName,
                loopIndex,
                request,
                toolCallId,
                toolName,
                toolArguments,
                toolResult,
                metadata,
                assistantMessage == null ? "" : assistantMessage,
                errorMessage
        );
    }

    public AgentLoopHookContext withError(String errorMessage) {
        return new AgentLoopHookContext(
                eventName,
                requestId,
                agentName,
                loopIndex,
                request,
                toolCallId,
                toolName,
                toolArguments,
                toolResult,
                metadata,
                assistantMessage,
                errorMessage == null ? "" : errorMessage
        );
    }
}
