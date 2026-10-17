package com.sinrotic.rs.agent.domain.session;

import java.time.Instant;
import java.util.Map;

/**
 * Append-only transcript entry. The session-local seq is the canonical replay order.
 */
public record AgentTranscriptEntry(
        String sessionId,
        long seq,
        long turnNo,
        int entryIndex,
        String requestId,
        String entryType,
        String role,
        Map<String, Object> payload,
        Instant createdAt
) {

    public AgentTranscriptEntry {
        payload = payload == null ? Map.of() : Map.copyOf(payload);
        createdAt = createdAt == null ? Instant.EPOCH : createdAt;
    }
}
