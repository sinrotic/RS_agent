package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptCheckpoint;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry;
import com.sinrotic.rs.agent.service.AgentSessionProjectionStore;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import javax.sql.DataSource;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Arrays;
import java.util.function.Consumer;

public class MysqlAgentSessionProjectionStore implements AgentSessionProjectionStore {

    private final SqlExecutor sqlExecutor;

    private final ObjectMapper objectMapper;

    public MysqlAgentSessionProjectionStore(SqlExecutor sqlExecutor, ObjectMapper objectMapper) {
        this.sqlExecutor = sqlExecutor;
        this.objectMapper = objectMapper;
    }

    public static ObjectMapper defaultObjectMapper() {
        return new ObjectMapper().findAndRegisterModules();
    }

    @Override
    public void recordSessionEvent(AgentSessionEvent event) {
        sqlExecutor.inTransaction(executor -> recordSessionEvent(executor, event));
    }

    private void recordSessionEvent(SqlExecutor executor, AgentSessionEvent event) {
        Instant occurredAt = event.occurredAt() == null ? Instant.EPOCH : event.occurredAt();
        executor.update(
                """
                        INSERT INTO agent_sessions (
                            session_id, last_request_id, last_event_type, last_loop_index, last_event_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON DUPLICATE KEY UPDATE
                            last_request_id = VALUES(last_request_id),
                            last_event_type = VALUES(last_event_type),
                            last_loop_index = VALUES(last_loop_index),
                            last_event_at = GREATEST(last_event_at, VALUES(last_event_at)),
                            updated_at = VALUES(updated_at)
                        """,
                event.sessionId(),
                event.requestId(),
                event.eventType(),
                event.loopIndex(),
                occurredAt,
                occurredAt
        );
        if (!event.toolCallId().isBlank()) {
            executor.update(
                    """
                            INSERT INTO agent_tool_calls (
                                session_id, tool_call_id, request_id, tool_name, status, error_code, last_event_type,
                                updated_at, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON DUPLICATE KEY UPDATE
                                request_id = VALUES(request_id),
                                tool_name = VALUES(tool_name),
                                status = VALUES(status),
                                error_code = VALUES(error_code),
                                last_event_type = VALUES(last_event_type),
                                updated_at = VALUES(updated_at)
                            """,
                    event.sessionId(),
                    event.toolCallId(),
                    event.requestId(),
                    stringPayload(event, "tool_name"),
                    stringPayload(event, "status"),
                    stringPayload(event, "error_code"),
                    event.eventType(),
                    occurredAt,
                    occurredAt
            );
        }
    }

    @Override
    public void recordTranscriptEntry(AgentTranscriptEntry entry) {
        sqlExecutor.inTransaction(executor -> recordTranscriptEntry(executor, entry));
    }

    private void recordTranscriptEntry(SqlExecutor executor, AgentTranscriptEntry entry) {
        Instant createdAt = entry.createdAt() == null ? Instant.EPOCH : entry.createdAt();
        String userId = stringPayload(entry, "profile_user_id");
        executor.update(
                """
                        INSERT INTO agent_sessions (
                            session_id, user_id, last_request_id, last_seq, last_entry_type, last_entry_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON DUPLICATE KEY UPDATE
                            user_id = IF(VALUES(user_id) = '', user_id, VALUES(user_id)),
                            last_request_id = VALUES(last_request_id),
                            last_seq = GREATEST(COALESCE(last_seq, 0), VALUES(last_seq)),
                            last_entry_type = VALUES(last_entry_type),
                            last_entry_at = GREATEST(COALESCE(last_entry_at, '1970-01-01 00:00:00'), VALUES(last_entry_at)),
                            updated_at = VALUES(updated_at)
                """,
                entry.sessionId(),
                userId,
                entry.requestId(),
                entry.seq(),
                entry.entryType(),
                createdAt,
                createdAt
        );
        executor.update(
                """
                        INSERT INTO agent_turns (
                            session_id, turn_no, first_seq, last_seq, request_id, last_entry_type, last_role,
                            updated_at, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON DUPLICATE KEY UPDATE
                            first_seq = LEAST(first_seq, VALUES(first_seq)),
                            last_seq = GREATEST(last_seq, VALUES(last_seq)),
                            request_id = VALUES(request_id),
                            last_entry_type = VALUES(last_entry_type),
                            last_role = VALUES(last_role),
                            updated_at = VALUES(updated_at)
                        """,
                entry.sessionId(),
                entry.turnNo(),
                entry.seq(),
                entry.seq(),
                entry.requestId(),
                entry.entryType(),
                entry.role(),
                createdAt,
                createdAt
        );
        recordToolCall(executor, entry, createdAt);
    }

    @Override
    public void recordCheckpoint(AgentTranscriptCheckpoint checkpoint) {
        sqlExecutor.inTransaction(executor -> recordCheckpoint(executor, checkpoint));
    }

    private void recordCheckpoint(SqlExecutor executor, AgentTranscriptCheckpoint checkpoint) {
        Instant createdAt = checkpoint.createdAt() == null ? Instant.EPOCH : checkpoint.createdAt();
        executor.update(
                """
                        INSERT INTO agent_checkpoints (
                            session_id, checkpoint_id, checkpoint_seq, summary_messages_json, preserved_entries_json,
                            source_entry_count, source_token_count, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON DUPLICATE KEY UPDATE
                            checkpoint_seq = VALUES(checkpoint_seq),
                            summary_messages_json = VALUES(summary_messages_json),
                            preserved_entries_json = VALUES(preserved_entries_json),
                            source_entry_count = VALUES(source_entry_count),
                            source_token_count = VALUES(source_token_count),
                            updated_at = VALUES(updated_at)
                        """,
                checkpoint.sessionId(),
                checkpoint.checkpointId(),
                checkpoint.checkpointSeq(),
                write(checkpoint.summaryMessages()),
                write(checkpoint.preservedEntries()),
                checkpoint.sourceEntryCount(),
                checkpoint.sourceTokenCount(),
                createdAt,
                createdAt
        );
        executor.update(
                """
                        UPDATE agent_sessions
                        SET latest_checkpoint_id = ?, checkpoint_seq = ?, updated_at = ?
                        WHERE session_id = ?
                        """,
                checkpoint.checkpointId(),
                checkpoint.checkpointSeq(),
                createdAt,
                checkpoint.sessionId()
        );
    }

    private String stringPayload(AgentSessionEvent event, String key) {
        Object value = event.payload().get(key);
        return value == null ? "" : String.valueOf(value);
    }

    private String stringPayload(AgentTranscriptEntry entry, String key) {
        Object value = entry.payload().get(key);
        return value == null ? "" : String.valueOf(value);
    }

    private void recordToolCall(SqlExecutor executor, AgentTranscriptEntry entry, Instant createdAt) {
        String toolCallId = stringPayload(entry, "tool_call_id");
        if (toolCallId.isBlank()) {
            return;
        }
        executor.update(
                """
                        INSERT INTO agent_tool_calls (
                            session_id, tool_call_id, request_id, tool_name, status, error_code, last_event_type,
                            updated_at, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON DUPLICATE KEY UPDATE
                            request_id = VALUES(request_id),
                            tool_name = VALUES(tool_name),
                            status = VALUES(status),
                            error_code = VALUES(error_code),
                            last_event_type = VALUES(last_event_type),
                            updated_at = VALUES(updated_at)
                        """,
                entry.sessionId(),
                toolCallId,
                entry.requestId(),
                stringPayload(entry, "tool_name"),
                stringPayload(entry, "status"),
                stringPayload(entry, "error_code"),
                entry.entryType(),
                createdAt,
                createdAt
        );
    }

    private String write(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("failed to serialize agent session projection payload", error);
        }
    }

    public interface SqlExecutor {
        void update(String sql, Object... args);

        default void inTransaction(Consumer<SqlExecutor> operation) {
            operation.accept(this);
        }
    }

    public static class DataSourceSqlExecutor implements SqlExecutor {

        private final JdbcTemplate jdbc;
        private final TransactionTemplate transaction;

        public DataSourceSqlExecutor(DataSource dataSource) {
            this.jdbc = new JdbcTemplate(dataSource);
            this.transaction = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
        }

        @Override
        public void inTransaction(Consumer<SqlExecutor> operation) {
            transaction.executeWithoutResult(status -> operation.accept(this));
        }

        @Override
        public void update(String sql, Object... args) {
            jdbc.update(sql, Arrays.stream(args).map(this::sqlValue).toArray());
        }

        private Object sqlValue(Object value) {
            if (value instanceof Instant instant) {
                return Timestamp.from(instant);
            }
            return value;
        }
    }
}
