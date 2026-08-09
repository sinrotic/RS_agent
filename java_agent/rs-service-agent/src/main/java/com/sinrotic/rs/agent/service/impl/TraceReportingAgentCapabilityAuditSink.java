package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.AgentCapabilityAuditEvent;
import com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.agent.service.AgentCapabilityAuditSink;
import com.sinrotic.rs.agent.service.AgentTraceReporter;

import java.util.Map;
import java.util.UUID;

public class TraceReportingAgentCapabilityAuditSink implements AgentCapabilityAuditSink {

    private final AgentTraceReporter traceReporter;

    public TraceReportingAgentCapabilityAuditSink(AgentTraceReporter traceReporter) {
        this.traceReporter = traceReporter;
    }

    @Override
    public void record(AgentCapabilityAuditEvent event) {
        traceReporter.report(new AgentTraceEventVO(
                "evt_" + UUID.randomUUID().toString().substring(0, 8),
                "",
                event.requestId(),
                "capability_result",
                "",
                event.capabilityId(),
                event.profileId(),
                "",
                "",
                null,
                null,
                null,
                null,
                null,
                null,
                "capability",
                event.status().equals("SUCCESS") ? "success" : "error",
                event.errorCode(),
                event.errorMessage(),
                "",
                "",
                Map.of("capability_id", event.capabilityId()),
                event.occurredAt()
        ));
    }
}
