package com.sinrotic.rs.agent.service;

import com.datastax.oss.driver.api.core.CqlSession;
import com.datastax.oss.driver.api.core.cql.ResultSet;
import com.datastax.oss.driver.api.core.cql.Row;
import com.datastax.oss.driver.api.core.cql.SimpleStatement;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.memory.AgentMemoryItem;
import com.sinrotic.rs.agent.service.impl.ScyllaAgentMemoryItemStore;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ScyllaAgentMemoryItemStoreTest {

    @Test
    void savesMemoryItemWithContentAndMetadataInSingleScyllaTable() {
        CqlSession session = mock(CqlSession.class);
        when(session.execute(any(SimpleStatement.class))).thenReturn(mock(ResultSet.class));
        ScyllaAgentMemoryItemStore store = new ScyllaAgentMemoryItemStore(session, objectMapper());

        store.save(memoryItem());

        ArgumentCaptor<SimpleStatement> statementCaptor = ArgumentCaptor.forClass(SimpleStatement.class);
        verify(session).execute(statementCaptor.capture());
        SimpleStatement statement = statementCaptor.getValue();
        assertThat(statement.getQuery()).contains("INSERT INTO agent_memory_items_by_user");
        assertThat(statement.getQuery()).doesNotContain("agent_memory_item_meta");
        assertThat(statement.getPositionalValues()).contains(
                "tenant_001",
                "profile_user_001",
                "mem_001",
                "user",
                "user_budget_preference",
                "User prefers good value",
                "high",
                8,
                "active",
                "User prefers good value and avoids obviously overpriced items.",
                "sess_001",
                3,
                "hash_001"
        );
    }

    @Test
    void findsMemoryItemByIndexPointerKey() {
        CqlSession session = mock(CqlSession.class);
        ResultSet resultSet = mock(ResultSet.class);
        Row row = mock(Row.class);
        when(session.execute(any(SimpleStatement.class))).thenReturn(resultSet);
        when(resultSet.one()).thenReturn(row);
        when(row.getString("tenant_id")).thenReturn("tenant_001");
        when(row.getString("profile_user_id")).thenReturn("profile_user_001");
        when(row.getString("memory_id")).thenReturn("mem_001");
        when(row.getString("memory_type")).thenReturn("user");
        when(row.getString("name")).thenReturn("user_budget_preference");
        when(row.getString("summary")).thenReturn("User prefers good value");
        when(row.getString("confidence")).thenReturn("high");
        when(row.getInt("importance")).thenReturn(8);
        when(row.getString("status")).thenReturn("active");
        when(row.getString("content")).thenReturn("User prefers good value and avoids obviously overpriced items.");
        when(row.getString("source_session_id")).thenReturn("sess_001");
        when(row.getString("metadata_json")).thenReturn("{\"source\":\"explicit\"}");
        when(row.getInt("version")).thenReturn(3);
        when(row.getString("content_hash")).thenReturn("hash_001");
        when(row.getInstant("updated_at")).thenReturn(Instant.parse("2026-07-09T02:00:00Z"));
        ScyllaAgentMemoryItemStore store = new ScyllaAgentMemoryItemStore(session, objectMapper());

        Optional<AgentMemoryItem> item = store.findById("tenant_001", "profile_user_001", "mem_001");

        assertThat(item).hasValueSatisfying(value -> {
            assertThat(value.memoryId()).isEqualTo("mem_001");
            assertThat(value.metadata()).containsEntry("source", "explicit");
            assertThat(value.content()).contains("good value");
        });
        ArgumentCaptor<SimpleStatement> statementCaptor = ArgumentCaptor.forClass(SimpleStatement.class);
        verify(session).execute(statementCaptor.capture());
        assertThat(statementCaptor.getValue().getQuery())
                .contains("WHERE tenant_id = ? AND profile_user_id = ? AND memory_id = ?");
    }

    @Test
    void rejectsContentLargerThanSixtyFourKilobytes() {
        CqlSession session = mock(CqlSession.class);
        ScyllaAgentMemoryItemStore store = new ScyllaAgentMemoryItemStore(session, objectMapper());
        String oversizedContent = "x".repeat(64 * 1024 + 1);
        AgentMemoryItem oversized = new AgentMemoryItem(
                "tenant_001",
                "profile_user_001",
                "mem_oversized",
                "reference",
                "large_reference",
                "Large reference",
                "medium",
                3,
                "active",
                oversizedContent,
                "sess_001",
                Map.of(),
                1,
                "hash_oversized",
                Instant.parse("2026-07-09T02:00:00Z")
        );

        assertThatThrownBy(() -> store.save(oversized))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("64KB");
    }

    private AgentMemoryItem memoryItem() {
        return new AgentMemoryItem(
                "tenant_001",
                "profile_user_001",
                "mem_001",
                "user",
                "user_budget_preference",
                "User prefers good value",
                "high",
                8,
                "active",
                "User prefers good value and avoids obviously overpriced items.",
                "sess_001",
                Map.of("source", "explicit"),
                3,
                "hash_001",
                Instant.parse("2026-07-09T02:00:00Z")
        );
    }

    private ObjectMapper objectMapper() {
        return new ObjectMapper().findAndRegisterModules();
    }
}
