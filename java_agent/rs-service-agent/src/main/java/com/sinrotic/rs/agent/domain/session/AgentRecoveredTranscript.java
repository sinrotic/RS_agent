package com.sinrotic.rs.agent.domain.session;

import java.util.List;
import java.util.Map;

/**
 * Replay input rebuilt from a ScyllaDB checkpoint plus append-only transcript tail.
 */
public record AgentRecoveredTranscript(
        String sessionId,
        String checkpointId,
        long checkpointSeq,
        List<Map<String, Object>> summaryMessages,
        List<Map<String, Object>> preservedEntries,
        List<AgentTranscriptEntry> tailEntries
) {

    public AgentRecoveredTranscript {
        checkpointId = checkpointId == null ? "" : checkpointId;
        summaryMessages = copyPayloadList(summaryMessages);
        preservedEntries = copyPayloadList(preservedEntries);
        tailEntries = tailEntries == null ? List.of() : List.copyOf(tailEntries);
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
