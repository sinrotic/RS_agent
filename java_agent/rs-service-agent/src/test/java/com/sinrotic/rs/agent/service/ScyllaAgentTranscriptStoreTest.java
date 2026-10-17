package com.sinrotic.rs.agent.service;

import com.datastax.oss.driver.api.core.CqlSession;
import com.datastax.oss.driver.api.core.cql.ResultSet;
import com.datastax.oss.driver.api.core.cql.Row;
import com.datastax.oss.driver.api.core.cql.SimpleStatement;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptCheckpoint;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry;
import com.sinrotic.rs.agent.service.impl.NoopAgentSessionProjectionStore;
import com.sinrotic.rs.agent.service.impl.ScyllaAgentTranscriptCheckpointStore;
import com.sinrotic.rs.agent.service.impl.ScyllaAgentTranscriptEntryStore;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ScyllaAgentTranscriptStoreTest {

    @Test
    void entryStoreAppendsJsonPayloadAndReadsTailInSeqOrder() {
        CqlSession session = mock(CqlSession.class);
        ResultSet resultSet = mock(ResultSet.class);
        Row row = mock(Row.class);
        when(session.execute(any(SimpleStatement.class))).thenReturn(resultSet);
        when(resultSet.all()).thenReturn(List.of(row));
        when(row.getString("session_id")).thenReturn("sess_001");
        when(row.getLong("seq")).thenReturn(3L);
        when(row.getLong("turn_no")).thenReturn(2L);
        when(row.getInt("entry_index")).thenReturn(0);
        when(row.getString("request_id")).thenReturn("agent_req_002");
        when(row.getString("entry_type")).thenReturn("USER_MESSAGE");
        when(row.getString("role")).thenReturn("user");
        when(row.getString("payload_json")).thenReturn("{\"content\":\"hello\"}");
        when(row.getInstant("created_at")).thenReturn(Instant.parse("2026-07-07T08:00:03Z"));
        ScyllaAgentTranscriptEntryStore store = new ScyllaAgentTranscriptEntryStore(
                session,
                objectMapper()
        );

        store.append(new AgentTranscriptEntry(
                "sess_001",
                3L,
                2L,
                0,
                "agent_req_002",
                "USER_MESSAGE",
                "user",
                Map.of("content", "hello"),
                Instant.parse("2026-07-07T08:00:03Z")
        ));
        List<AgentTranscriptEntry> tail = store.tailAfter("sess_001", 2L);

        ArgumentCaptor<SimpleStatement> statementCaptor = ArgumentCaptor.forClass(SimpleStatement.class);
        verify(session, org.mockito.Mockito.times(2)).execute(statementCaptor.capture());
        assertThat(statementCaptor.getAllValues().getFirst().getQuery())
                .contains("INSERT INTO agent_transcript_entries_by_session");
        assertThat(statementCaptor.getAllValues().getLast().getQuery())
                .contains("WHERE session_id = ? AND seq > ?");
        assertThat(tail)
                .extracting(AgentTranscriptEntry::seq)
                .containsExactly(3L);
        assertThat(tail.getFirst().payload()).containsEntry("content", "hello");
    }

    @Test
    void checkpointStoreSavesJsonListsAndReadsLatestCheckpoint() {
        CqlSession session = mock(CqlSession.class);
        ResultSet resultSet = mock(ResultSet.class);
        Row row = mock(Row.class);
        when(session.execute(any(SimpleStatement.class))).thenReturn(resultSet);
        when(resultSet.one()).thenReturn(row);
        when(row.getString("checkpoint_id")).thenReturn("cp_001");
        when(row.getString("session_id")).thenReturn("sess_001");
        when(row.getLong("checkpoint_seq")).thenReturn(8L);
        when(row.getString("summary_messages_json")).thenReturn("[{\"role\":\"system\",\"content\":\"summary\"}]");
        when(row.getString("preserved_entries_json")).thenReturn("[{\"seq\":7}]");
        when(row.getInt("source_entry_count")).thenReturn(8);
        when(row.getInt("source_token_count")).thenReturn(256);
        when(row.getInstant("created_at")).thenReturn(Instant.parse("2026-07-07T08:00:08Z"));
        ScyllaAgentTranscriptCheckpointStore store = new ScyllaAgentTranscriptCheckpointStore(
                session,
                objectMapper()
        );

        store.save(new AgentTranscriptCheckpoint(
                "cp_001",
                "sess_001",
                8L,
                List.of(Map.of("role", "system", "content", "summary")),
                List.of(Map.of("seq", 7L)),
                8,
                256,
                Instant.parse("2026-07-07T08:00:08Z")
        ));

        assertThat(store.latest("sess_001"))
                .hasValueSatisfying(checkpoint -> {
                    assertThat(checkpoint.checkpointId()).isEqualTo("cp_001");
                    assertThat(checkpoint.checkpointSeq()).isEqualTo(8L);
                    assertThat(checkpoint.summaryMessages().getFirst()).containsEntry("content", "summary");
                });
    }

    private ObjectMapper objectMapper() {
        return new ObjectMapper().findAndRegisterModules();
    }

}
