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
        AgentInterruptContext context = new AgentInterruptContext(requestId, sessionId);
        turns.put(requestId, context);
        return context;
    }

    @Override
    public boolean interrupt(String requestId, String reason) {
        AgentInterruptContext context = turns.get(requestId);
        return context != null && context.interrupt(reason);
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
