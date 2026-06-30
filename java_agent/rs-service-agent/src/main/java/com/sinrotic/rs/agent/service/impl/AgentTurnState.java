package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentToolCallVO;

import java.util.List;
import java.util.Map;
import java.util.Optional;

public record AgentTurnState(
        String requestId,
        String sessionId,
        AgentChatRequestDTO request,
        StringBuilder assistantMessage,
        List<AgentToolCallVO> toolCalls,
        List<Map<String, Object>> toolResults,
        Map<String, Object> modelUsage,
        AgentInterruptContext interruptContext,
        int loopIndex,
        AgentLoopPhase phase,
        AgentLoopTransition transition,
        PendingToolCall pendingToolCall
) {
    public AgentTurnState withRequest(AgentChatRequestDTO request) {
        return new AgentTurnState(requestId, sessionId, request, assistantMessage, toolCalls, toolResults,
                modelUsage, interruptContext, loopIndex, phase, transition, pendingToolCall);
    }

    public AgentTurnState withLoopIndex(int loopIndex) {
        return new AgentTurnState(requestId, sessionId, request, assistantMessage, toolCalls, toolResults,
                modelUsage, interruptContext, loopIndex, phase, transition, pendingToolCall);
    }

    public AgentTurnState withPhase(AgentLoopPhase phase) {
        return new AgentTurnState(requestId, sessionId, request, assistantMessage, toolCalls, toolResults,
                modelUsage, interruptContext, loopIndex, phase, transition, pendingToolCall);
    }

    public AgentTurnState withTransition(AgentLoopTransition transition) {
        return new AgentTurnState(requestId, sessionId, request, assistantMessage, toolCalls, toolResults,
                modelUsage, interruptContext, loopIndex, phase, transition, pendingToolCall);
    }

    public AgentTurnState withPendingToolCall(PendingToolCall pendingToolCall) {
        return new AgentTurnState(requestId, sessionId, request, assistantMessage, toolCalls, toolResults,
                modelUsage, interruptContext, loopIndex, phase, transition, pendingToolCall);
    }

    public AgentTurnState clearPendingToolCall() {
        return withPendingToolCall(null);
    }

    public Optional<PendingToolCall> pendingTool() {
        return Optional.ofNullable(pendingToolCall);
    }
}
