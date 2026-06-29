package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.vo.AgentSessionTraceVO;

public interface AgentTraceService {

    AgentSessionTraceVO sessionTurns(String sessionId);

    AgentSessionTraceVO platformSessionTrace(String sessionId);
}
