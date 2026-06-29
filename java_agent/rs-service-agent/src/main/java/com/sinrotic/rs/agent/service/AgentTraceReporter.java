package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO;

@FunctionalInterface
public interface AgentTraceReporter {

    void report(AgentTraceEventVO event);
}
