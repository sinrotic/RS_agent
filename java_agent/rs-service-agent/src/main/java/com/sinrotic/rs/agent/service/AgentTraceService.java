package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.vo.AgentSessionTraceVO;

public interface AgentTraceService {

    AgentSessionTraceVO sessionTurns(String sessionId);

    default AgentSessionTraceVO sessionTurns(String sessionId, String profileUserId) {
        return sessionTurns(sessionId);
    }

    default AgentSessionTraceVO sessionTurns(String sessionId, String profileUserId, String accountId) {
        throw new AgentSessionNotFoundException();
    }

    AgentSessionTraceVO platformSessionTrace(String sessionId);
}
