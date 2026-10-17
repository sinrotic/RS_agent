package com.sinrotic.rs.agent.service.impl;

import com.datastax.oss.driver.api.core.CqlSession;
import com.datastax.oss.driver.api.core.cql.Row;
import com.datastax.oss.driver.api.core.cql.SimpleStatement;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentSessionSnapshot;
import com.sinrotic.rs.agent.service.AgentColdSessionArchiveStore;
import com.sinrotic.rs.agent.service.AgentSessionProjectionStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

@Service
@Primary
@ConditionalOnProperty(prefix = "rs.agent.session-persistence", name = "enabled", havingValue = "true")
public class ScyllaAgentColdSessionArchiveStore implements AgentColdSessionArchiveStore {

    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    private final CqlSession cqlSession;

    private final ObjectMapper objectMapper;

    private final AgentSessionProjectionStore projectionStore;

    public ScyllaAgentColdSessionArchiveStore(
            CqlSession cqlSession,
            ObjectMapper objectMapper,
            AgentSessionProjectionStore projectionStore
    ) {
        this.cqlSession = cqlSession;
        this.objectMapper = objectMapper;
        this.projectionStore = projectionStore;
    }

    @Override
    public void archiveEvents(List<AgentSessionEvent> events) {
        for (AgentSessionEvent event : events == null ? List.<AgentSessionEvent>of() : events) {
            cqlSession.execute(SimpleStatement.newInstance(
                    """
                            INSERT INTO agent_session_events_by_session (
                                session_id, occurred_at, event_id, request_id, event_type, loop_index, tool_call_id,
                                payload_json, payload_ref, compaction_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                    event.sessionId(),
                    event.occurredAt(),
                    event.eventId(),
                    event.requestId(),
                    event.eventType(),
                    event.loopIndex(),
                    event.toolCallId(),
                    write(event.payload()),
                    event.payloadRef(),
                    event.compactionId()
            ));
            projectionStore.recordSessionEvent(event);
        }
    }

    @Override
    public void archiveSnapshot(AgentSessionSnapshot snapshot) {
        cqlSession.execute(SimpleStatement.newInstance(
                """
                        INSERT INTO agent_session_snapshots_by_session (
                            session_id, snapshot_time, snapshot_id, compaction_id, compact_before_event_id,
                            source_event_count, source_token_count, summary_payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                snapshot.sessionId(),
                snapshot.snapshotTime(),
                snapshot.snapshotId(),
                snapshot.compactionId(),
                snapshot.compactBeforeEventId(),
                snapshot.sourceEventCount(),
                snapshot.sourceTokenCount(),
                write(snapshot.summaryPayload())
        ));
    }

    @Override
    public List<AgentSessionEvent> events(String sessionId) {
        return cqlSession.execute(SimpleStatement.newInstance(
                        """
                                SELECT session_id, occurred_at, event_id, request_id, event_type, loop_index,
                                       tool_call_id, payload_json, payload_ref, compaction_id
                                FROM agent_session_events_by_session
                                WHERE session_id = ?
                                ORDER BY occurred_at ASC, event_id ASC
                                """,
                        sessionId
                ))
                .all()
                .stream()
                .map(this::readEvent)
                .toList();
    }

    @Override
    public List<AgentSessionSnapshot> snapshots(String sessionId) {
        return cqlSession.execute(SimpleStatement.newInstance(
                        """
                                SELECT session_id, snapshot_time, snapshot_id, compaction_id, compact_before_event_id,
                                       source_event_count, source_token_count, summary_payload_json
                                FROM agent_session_snapshots_by_session
                                WHERE session_id = ?
                                ORDER BY snapshot_time ASC, snapshot_id ASC
                                """,
                        sessionId
                ))
                .all()
                .stream()
                .map(this::readSnapshot)
                .toList();
    }

    private AgentSessionEvent readEvent(Row row) {
        return new AgentSessionEvent(
                row.getString("event_id"),
                row.getString("session_id"),
                row.getString("request_id"),
                row.getString("event_type"),
                row.getInt("loop_index"),
                row.getString("tool_call_id"),
                readMap(row.getString("payload_json")),
                row.getString("payload_ref"),
                row.getString("compaction_id"),
                row.getInstant("occurred_at")
        );
    }

    private AgentSessionSnapshot readSnapshot(Row row) {
        return new AgentSessionSnapshot(
                row.getString("snapshot_id"),
                row.getString("session_id"),
                row.getString("compaction_id"),
                row.getString("compact_before_event_id"),
                row.getInt("source_event_count"),
                row.getInt("source_token_count"),
                readMap(row.getString("summary_payload_json")),
                row.getInstant("snapshot_time")
        );
    }

    private String write(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("failed to serialize cold agent session payload", error);
        }
    }

    private Map<String, Object> readMap(String value) {
        if (value == null || value.isBlank()) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(value, MAP_TYPE);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("failed to deserialize cold agent session payload", error);
        }
    }
}
