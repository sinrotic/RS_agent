package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.AgentInterruptContext;

public interface AgentInterrupter {

    AgentInterruptContext createTurn(String requestId, String sessionId);

    boolean interrupt(String requestId, String reason);

    boolean isInterrupted(String requestId);

    void close(String requestId);
}
