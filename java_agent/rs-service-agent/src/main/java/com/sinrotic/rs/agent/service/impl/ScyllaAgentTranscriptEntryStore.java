package com.sinrotic.rs.agent.service.impl;

import com.datastax.oss.driver.api.core.CqlSession;
import com.datastax.oss.driver.api.core.cql.Row;
import com.datastax.oss.driver.api.core.cql.SimpleStatement;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry;
import com.sinrotic.rs.agent.service.AgentTranscriptEntryStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.Optional;

@Service
@Primary
@ConditionalOnProperty(prefix = "rs.agent.session-persistence", name = "enabled", havingValue = "true")
public class ScyllaAgentTranscriptEntryStore implements AgentTranscriptEntryStore {

    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    private final CqlSession cqlSession;

    private final ObjectMapper objectMapper;

    public ScyllaAgentTranscriptEntryStore(
            CqlSession cqlSession,
            ObjectMapper objectMapper
    ) {
        this.cqlSession = cqlSession;
        this.objectMapper = objectMapper;
    }

    @Override
    public void append(AgentTranscriptEntry entry) {
        cqlSession.execute(SimpleStatement.newInstance(
                """
                        INSERT INTO agent_transcript_entries_by_session (
                            session_id, seq, turn_no, entry_index, request_id, entry_type, role, payload_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                entry.sessionId(),
                entry.seq(),
                entry.turnNo(),
                entry.entryIndex(),
                entry.requestId(),
                entry.entryType(),
                entry.role(),
                write(entry.payload()),
                entry.createdAt()
        ));
    }

    @Override
    public Optional<AgentTranscriptEntry> latest(String sessionId) {
        Row row = cqlSession.execute(SimpleStatement.newInstance(
                """
                        SELECT session_id, seq, turn_no, entry_index, request_id, entry_type, role,
                               payload_json, created_at
                        FROM agent_transcript_entries_by_session
                        WHERE session_id = ?
                        ORDER BY seq DESC
                        LIMIT 1
                        """,
                sessionId
        )).one();
        return row == null ? Optional.empty() : Optional.of(readEntry(row));
    }

    @Override
    public List<AgentTranscriptEntry> tailAfter(String sessionId, long exclusiveSeq) {
        return cqlSession.execute(SimpleStatement.newInstance(
                        """
                                SELECT session_id, seq, turn_no, entry_index, request_id, entry_type, role,
                                       payload_json, created_at
                                FROM agent_transcript_entries_by_session
                                WHERE session_id = ? AND seq > ?
                                ORDER BY seq ASC
                                """,
                        sessionId,
                        exclusiveSeq
                ))
                .all()
                .stream()
                .map(this::readEntry)
                .toList();
    }

    private AgentTranscriptEntry readEntry(Row row) {
        return new AgentTranscriptEntry(
                row.getString("session_id"),
                row.getLong("seq"),
                row.getLong("turn_no"),
                row.getInt("entry_index"),
                row.getString("request_id"),
                row.getString("entry_type"),
                row.getString("role"),
                readMap(row.getString("payload_json")),
                row.getInstant("created_at")
        );
    }

    private String write(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("failed to serialize agent transcript payload", error);
        }
    }

    private Map<String, Object> readMap(String value) {
        if (value == null || value.isBlank()) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(value, MAP_TYPE);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("failed to deserialize agent transcript payload", error);
        }
    }
}
