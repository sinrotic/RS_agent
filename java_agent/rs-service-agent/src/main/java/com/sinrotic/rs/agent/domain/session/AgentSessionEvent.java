package com.sinrotic.rs.agent.domain.session;

import java.time.Instant;
import java.util.Map;

/**
 * Append-only event for one agent conversation.
 */
public record AgentSessionEvent(
        String eventId,
        String sessionId,
        String requestId,
        String eventType,
        int loopIndex,
        String toolCallId,
        Map<String, Object> payload,
        String payloadRef,
        String compactionId,
        Instant occurredAt
) {

    public AgentSessionEvent {
        payload = payload == null ? Map.of() : Map.copyOf(payload);
        payloadRef = payloadRef == null ? "" : payloadRef;
        compactionId = compactionId == null ? "" : compactionId;
        toolCallId = toolCallId == null ? "" : toolCallId;
    }
}
