package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.AgentCapabilityAuditEvent;

@FunctionalInterface
public interface AgentCapabilityAuditSink {

    void record(AgentCapabilityAuditEvent event);
}
