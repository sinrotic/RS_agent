package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry;
import com.sinrotic.rs.agent.service.AgentHotSessionStore;
import com.sinrotic.rs.agent.service.AgentSessionJournal;
import com.sinrotic.rs.agent.service.AgentSessionProjectionStore;
import com.sinrotic.rs.agent.service.AgentTranscriptEntryStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Writes the authoritative transcript first, then refreshes repairable projections and hot state.
 */
@Service
public class DefaultAgentSessionJournal implements AgentSessionJournal {

    private static final Logger log = LoggerFactory.getLogger(DefaultAgentSessionJournal.class);

    private final AgentTranscriptEntryStore entryStore;

    private final AgentSessionProjectionStore projectionStore;

    private final AgentHotSessionStore hotSessionStore;

    public DefaultAgentSessionJournal(
            AgentTranscriptEntryStore entryStore,
            AgentSessionProjectionStore projectionStore,
            AgentHotSessionStore hotSessionStore
    ) {
        this.entryStore = entryStore;
        this.projectionStore = projectionStore;
        this.hotSessionStore = hotSessionStore;
    }

    @Override
    public java.util.List<AgentTranscriptEntry> transcript(String sessionId) {
        return entryStore.tailAfter(sessionId, 0);
    }

    @Override
    public java.util.Optional<AgentTranscriptEntry> latest(String sessionId) { return entryStore.latest(sessionId); }

    @Override
    public Turn beginTurn(TurnStart start) {
        AgentTranscriptEntry latest = entryStore.latest(start.sessionId()).orElse(null);
        return beginTurnAfter(start, latest);
    }

    @Override
    public Turn beginTurn(TurnStart start, java.util.List<AgentTranscriptEntry> transcript) {
        AgentTranscriptEntry latest = transcript.isEmpty() ? null : transcript.getLast();
        if (latest != null && !start.sessionId().equals(latest.sessionId())) {
            throw new IllegalArgumentException("transcript belongs to a different Session");
        }
        return beginTurnAfter(start, latest);
    }

    private Turn beginTurnAfter(TurnStart start, AgentTranscriptEntry latest) {
        long nextSeq = latest == null ? 1L : latest.seq() + 1L;
        long turnNo = latest == null ? 1L : latest.turnNo() + 1L;
        DefaultTurn turn = new DefaultTurn(start.sessionId(), start.requestId(), turnNo, nextSeq);

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("content", value(start.userMessage()));
        payload.put("profile_user_id", value(start.profileUserId()));
        payload.put("context", start.context());
        turn.append("USER_MESSAGE", "user", Map.copyOf(payload));
        return turn;
    }

    private final class DefaultTurn implements Turn {

        private final String sessionId;

        private final String requestId;

        private final long turnNo;

        private long nextSeq;

        private int nextEntryIndex;

        private DefaultTurn(String sessionId, String requestId, long turnNo, long nextSeq) {
            this.sessionId = sessionId;
            this.requestId = requestId;
            this.turnNo = turnNo;
            this.nextSeq = nextSeq;
        }

        @Override
        public synchronized AgentTranscriptEntry append(
                String entryType,
                String role,
                Map<String, Object> payload
        ) {
            Instant createdAt = Instant.now();
            AgentTranscriptEntry entry = new AgentTranscriptEntry(
                    sessionId,
                    nextSeq++,
                    turnNo,
                    nextEntryIndex++,
                    requestId,
                    value(entryType),
                    value(role),
                    payload,
                    createdAt
            );

            // This is the durability boundary. Failure must stop the Agent loop.
            entryStore.append(entry);
            updateProjection(entry);
            updateHotState(entry);
            return entry;
        }
    }

    private void updateProjection(AgentTranscriptEntry entry) {
        try {
            projectionStore.recordTranscriptEntry(entry);
        } catch (RuntimeException error) {
            log.warn("agent session projection update failed; it can be repaired from ScyllaDB: sessionId={}, seq={}",
                    entry.sessionId(), entry.seq(), error);
        }
    }

    private void updateHotState(AgentTranscriptEntry entry) {
        try {
            Map<String, Object> payload = new LinkedHashMap<>(entry.payload());
            payload.put("seq", entry.seq());
            payload.put("turn_no", entry.turnNo());
            payload.put("entry_index", entry.entryIndex());
            payload.put("role", entry.role());
            hotSessionStore.append(new AgentSessionEvent(
                    "evt_" + entry.sessionId() + "_" + entry.seq(),
                    entry.sessionId(),
                    entry.requestId(),
                    entry.entryType(),
                    0,
                    value(entry.payload().get("tool_call_id")),
                    Map.copyOf(payload),
                    "",
                    "",
                    entry.createdAt()
            ));
        } catch (RuntimeException error) {
            log.warn("agent hot session update failed; it can be rebuilt from ScyllaDB: sessionId={}, seq={}",
                    entry.sessionId(), entry.seq(), error);
        }
    }

    private static String value(Object value) {
        return value == null ? "" : String.valueOf(value);
    }
}
