package com.sinrotic.rs.agent.domain;

import java.time.Instant;

public record AgentCapabilityAuditEvent(
        String requestId,
        String profileId,
        String capabilityId,
        String status,
        String errorCode,
        String errorMessage,
        Instant occurredAt
) {
}
