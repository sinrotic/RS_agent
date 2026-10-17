package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry;

import java.util.Map;

/**
 * Durable semantic-event seam for one serialized Session Execution Lane.
 * Returning from {@link #beginTurn(TurnStart)} guarantees that USER_MESSAGE is durable.
 */
public interface AgentSessionJournal {

    Turn beginTurn(TurnStart start);

    /** Transcript must be authoritative and captured in this same serialized Session Execution Lane. */
    default Turn beginTurn(TurnStart start, java.util.List<AgentTranscriptEntry> transcript) {
        return beginTurn(start);
    }

    default java.util.List<AgentTranscriptEntry> transcript(String sessionId) {
        return java.util.List.of();
    }

    default java.util.Optional<AgentTranscriptEntry> latest(String sessionId) {
        var entries = transcript(sessionId);
        return entries.isEmpty() ? java.util.Optional.empty() : java.util.Optional.of(entries.getLast());
    }

    record TurnStart(
            String sessionId,
            String requestId,
            String profileUserId,
            String userMessage,
            Map<String, Object> context
    ) {

        public TurnStart {
            context = context == null ? Map.of() : Map.copyOf(context);
        }
    }

    interface Turn {

        AgentTranscriptEntry append(String entryType, String role, Map<String, Object> payload);
    }
}
