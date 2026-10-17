package com.sinrotic.rs.agent.service.impl;

import com.datastax.oss.driver.api.core.CqlSession;
import com.datastax.oss.driver.api.core.cql.Row;
import com.datastax.oss.driver.api.core.cql.SimpleStatement;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.memory.AgentMemoryItem;
import com.sinrotic.rs.agent.service.AgentMemoryItemStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.Optional;

@Service
@Primary
@ConditionalOnProperty(prefix = "rs.agent.session-persistence", name = "enabled", havingValue = "true")
public class ScyllaAgentMemoryItemStore implements AgentMemoryItemStore {

    private static final int MAX_CONTENT_BYTES = 64 * 1024;

    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    private final CqlSession cqlSession;

    private final ObjectMapper objectMapper;

    public ScyllaAgentMemoryItemStore(CqlSession cqlSession, ObjectMapper objectMapper) {
        this.cqlSession = cqlSession;
        this.objectMapper = objectMapper;
    }

    @Override
    public void save(AgentMemoryItem item) {
        validateContentSize(item);
        cqlSession.execute(SimpleStatement.newInstance(
                """
                        INSERT INTO agent_memory_items_by_user (
                            tenant_id, profile_user_id, memory_id, memory_type, name, summary,
                            confidence, importance, status, content, source_session_id,
                            metadata_json, version, content_hash, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                item.tenantId(),
                item.profileUserId(),
                item.memoryId(),
                item.type(),
                item.name(),
                item.summary(),
                item.confidence(),
                item.importance(),
                item.status(),
                item.content(),
                item.sourceSessionId(),
                write(item.metadata()),
                item.version(),
                item.contentHash(),
                item.updatedAt()
        ));
    }

    @Override
    public Optional<AgentMemoryItem> findById(String tenantId, String profileUserId, String memoryId) {
        Row row = cqlSession.execute(SimpleStatement.newInstance(
                        """
                                SELECT tenant_id, profile_user_id, memory_id, memory_type, name, summary,
                                       confidence, importance, status, content, source_session_id,
                                       metadata_json, version, content_hash, updated_at
                                FROM agent_memory_items_by_user
                                WHERE tenant_id = ? AND profile_user_id = ? AND memory_id = ?
                                """,
                        tenantId,
                        profileUserId,
                        memoryId
                ))
                .one();
        if (row == null) {
            return Optional.empty();
        }
        return Optional.of(readItem(row));
    }

    private AgentMemoryItem readItem(Row row) {
        return new AgentMemoryItem(
                row.getString("tenant_id"),
                row.getString("profile_user_id"),
                row.getString("memory_id"),
                row.getString("memory_type"),
                row.getString("name"),
                row.getString("summary"),
                row.getString("confidence"),
                row.getInt("importance"),
                row.getString("status"),
                row.getString("content"),
                row.getString("source_session_id"),
                readMap(row.getString("metadata_json")),
                row.getInt("version"),
                row.getString("content_hash"),
                row.getInstant("updated_at")
        );
    }

    private void validateContentSize(AgentMemoryItem item) {
        int contentBytes = item.content().getBytes(StandardCharsets.UTF_8).length;
        if (contentBytes > MAX_CONTENT_BYTES) {
            throw new IllegalArgumentException("agent memory content must be <= 64KB");
        }
    }

    private String write(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("failed to serialize agent memory metadata", error);
        }
    }

    private Map<String, Object> readMap(String value) {
        if (value == null || value.isBlank()) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(value, MAP_TYPE);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("failed to deserialize agent memory metadata", error);
        }
    }
}
