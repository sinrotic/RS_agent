package com.sinrotic.rs.agent.domain.session;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/**
 * Authoritative context checkpoint stored in ScyllaDB and used as the transcript replay boundary.
 */
public record AgentTranscriptCheckpoint(
        String checkpointId,
        String sessionId,
        long checkpointSeq,
        List<Map<String, Object>> summaryMessages,
        List<Map<String, Object>> preservedEntries,
        int sourceEntryCount,
        int sourceTokenCount,
        Instant createdAt
) {

    public AgentTranscriptCheckpoint {
        summaryMessages = copyPayloadList(summaryMessages);
        preservedEntries = copyPayloadList(preservedEntries);
        createdAt = createdAt == null ? Instant.EPOCH : createdAt;
    }

    private static List<Map<String, Object>> copyPayloadList(List<Map<String, Object>> payloadList) {
        if (payloadList == null) {
            return List.of();
        }
        return payloadList.stream()
                .map(payload -> payload == null ? Map.<String, Object>of() : Map.copyOf(payload))
                .toList();
    }
}
