package com.sinrotic.rs.agent.domain.session;

import java.time.Instant;
import java.util.Map;

/**
 * Compressed context checkpoint for cold session reload.
 */
public record AgentSessionSnapshot(
        String snapshotId,
        String sessionId,
        String compactionId,
        String compactBeforeEventId,
        int sourceEventCount,
        int sourceTokenCount,
        Map<String, Object> summaryPayload,
        Instant snapshotTime
) {

    public AgentSessionSnapshot {
        summaryPayload = summaryPayload == null ? Map.of() : Map.copyOf(summaryPayload);
    }
}
