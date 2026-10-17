package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.AgentInterruptContext;

public interface AgentInterrupter {

    AgentInterruptContext createTurn(String requestId, String sessionId);

    default AgentInterruptContext createTurn(String requestId, String sessionId, String profileUserId) {
        return createTurn(requestId, sessionId);
    }

    default AgentInterruptContext createTurn(String requestId, String sessionId, String accountId, String profileUserId) {
        return createTurn(requestId, sessionId, profileUserId);
    }

    boolean interrupt(String requestId, String reason);

    default boolean interruptOwned(String requestId, String profileUserId, String reason) {
        return false;
    }

    default boolean interruptOwned(String requestId, String accountId, String profileUserId, String reason) {
        return false;
    }

    boolean isInterrupted(String requestId);

    void close(String requestId);
}
