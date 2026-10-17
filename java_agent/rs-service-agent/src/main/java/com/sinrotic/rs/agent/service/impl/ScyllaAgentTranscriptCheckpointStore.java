package com.sinrotic.rs.agent.service.impl;

import com.datastax.oss.driver.api.core.CqlSession;
import com.datastax.oss.driver.api.core.cql.Row;
import com.datastax.oss.driver.api.core.cql.SimpleStatement;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptCheckpoint;
import com.sinrotic.rs.agent.service.AgentTranscriptCheckpointStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.Optional;

@Service
@Primary
@ConditionalOnProperty(prefix = "rs.agent.session-persistence", name = "enabled", havingValue = "true")
public class ScyllaAgentTranscriptCheckpointStore implements AgentTranscriptCheckpointStore {

    private static final TypeReference<List<Map<String, Object>>> LIST_MAP_TYPE = new TypeReference<>() {
    };

    private final CqlSession cqlSession;

    private final ObjectMapper objectMapper;

    public ScyllaAgentTranscriptCheckpointStore(
            CqlSession cqlSession,
            ObjectMapper objectMapper
    ) {
        this.cqlSession = cqlSession;
        this.objectMapper = objectMapper;
    }

    @Override
    public void save(AgentTranscriptCheckpoint checkpoint) {
        cqlSession.execute(SimpleStatement.newInstance(
                """
                        INSERT INTO agent_transcript_checkpoints_by_session (
                            session_id, checkpoint_seq, checkpoint_id, summary_messages_json, preserved_entries_json,
                            source_entry_count, source_token_count, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                checkpoint.sessionId(),
                checkpoint.checkpointSeq(),
                checkpoint.checkpointId(),
                write(checkpoint.summaryMessages()),
                write(checkpoint.preservedEntries()),
                checkpoint.sourceEntryCount(),
                checkpoint.sourceTokenCount(),
                checkpoint.createdAt()
        ));
    }

    @Override
    public Optional<AgentTranscriptCheckpoint> latest(String sessionId) {
        Row row = cqlSession.execute(SimpleStatement.newInstance(
                """
                        SELECT session_id, checkpoint_seq, checkpoint_id, summary_messages_json,
                               preserved_entries_json, source_entry_count, source_token_count, created_at
                        FROM agent_transcript_checkpoints_by_session
                        WHERE session_id = ?
                        LIMIT 1
                        """,
                sessionId
        )).one();
        return row == null ? Optional.empty() : Optional.of(readCheckpoint(row));
    }

    private AgentTranscriptCheckpoint readCheckpoint(Row row) {
        return new AgentTranscriptCheckpoint(
                row.getString("checkpoint_id"),
                row.getString("session_id"),
                row.getLong("checkpoint_seq"),
                readList(row.getString("summary_messages_json")),
                readList(row.getString("preserved_entries_json")),
                row.getInt("source_entry_count"),
                row.getInt("source_token_count"),
                row.getInstant("created_at")
        );
    }

    private String write(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("failed to serialize agent transcript checkpoint", error);
        }
    }

    private List<Map<String, Object>> readList(String value) {
        if (value == null || value.isBlank()) {
            return List.of();
        }
        try {
            return objectMapper.readValue(value, LIST_MAP_TYPE);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("failed to deserialize agent transcript checkpoint", error);
        }
    }
}
