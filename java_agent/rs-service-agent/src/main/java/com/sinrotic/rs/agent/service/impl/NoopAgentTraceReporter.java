package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.agent.service.AgentTraceReporter;

public class NoopAgentTraceReporter implements AgentTraceReporter {

    @Override
    public void report(AgentTraceEventVO event) {
    }
}
