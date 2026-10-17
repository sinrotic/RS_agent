package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO;

@FunctionalInterface
public interface AgentTraceReporter extends AutoCloseable {

    void report(AgentTraceEventVO event);

    @Override
    default void close() { }
}
