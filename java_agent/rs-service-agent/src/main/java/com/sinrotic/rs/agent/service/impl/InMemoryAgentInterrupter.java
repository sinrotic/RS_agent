package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.service.AgentInterrupter;
import org.springframework.stereotype.Service;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

@Service
public class InMemoryAgentInterrupter implements AgentInterrupter {

    private final ConcurrentMap<String, AgentInterruptContext> turns = new ConcurrentHashMap<>();

    @Override
    public AgentInterruptContext createTurn(String requestId, String sessionId) {
        return createTurn(requestId, sessionId, "");
    }

    @Override
    public AgentInterruptContext createTurn(String requestId, String sessionId, String profileUserId) {
        return createTurn(requestId, sessionId, "", profileUserId);
    }

    @Override
    public AgentInterruptContext createTurn(String requestId, String sessionId, String accountId, String profileUserId) {
        AgentInterruptContext context = new AgentInterruptContext(requestId, sessionId, accountId, profileUserId);
        turns.put(requestId, context);
        return context;
    }

    @Override
    public boolean interrupt(String requestId, String reason) {
        AgentInterruptContext context = turns.get(requestId);
        return context != null && context.interrupt(reason);
    }

    @Override
    public boolean interruptOwned(String requestId, String profileUserId, String reason) {
        AgentInterruptContext context = turns.get(requestId);
        if (context == null || !context.accountId().isBlank() || profileUserId == null || profileUserId.isBlank()) {
            return false;
        }
        return profileUserId.equals(context.profileUserId()) && context.interrupt(reason);
    }

    @Override
    public boolean interruptOwned(String requestId, String accountId, String profileUserId, String reason) {
        AgentInterruptContext context = turns.get(requestId);
        return context != null && accountId != null && !accountId.isBlank()
                && accountId.equals(context.accountId()) && profileUserId != null && !profileUserId.isBlank()
                && profileUserId.equals(context.profileUserId()) && context.interrupt(reason);
    }

    @Override
    public boolean isInterrupted(String requestId) {
        AgentInterruptContext context = turns.get(requestId);
        return context != null && context.interrupted();
    }

    @Override
    public void close(String requestId) {
        turns.remove(requestId);
    }
}
