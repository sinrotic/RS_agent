package com.sinrotic.rs.agent.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptCheckpoint;
import com.sinrotic.rs.agent.domain.session.AgentTranscriptEntry;
import com.sinrotic.rs.agent.service.impl.MysqlAgentSessionProjectionStore;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class JdbcAgentSessionProjectionStoreTest {

    @Test
    void recordsTranscriptEntryIntoSessionAndTurnProjectionTables() {
        CapturingSqlExecutor sqlExecutor = new CapturingSqlExecutor();
        MysqlAgentSessionProjectionStore store = new MysqlAgentSessionProjectionStore(
                sqlExecutor,
                new ObjectMapper().findAndRegisterModules()
        );

        store.recordTranscriptEntry(new AgentTranscriptEntry(
                "sess_001",
                3L,
                2L,
                0,
                "agent_req_002",
                "USER_MESSAGE",
                "user",
                Map.of("content", "hello", "profile_user_id", "user_001"),
                Instant.parse("2026-07-07T08:00:03Z")
        ));

        assertThat(sqlExecutor.calls).hasSize(2);
        assertThat(sqlExecutor.calls.getFirst().sql()).contains("INSERT INTO agent_sessions");
        assertThat(sqlExecutor.calls.getFirst().args())
                .containsExactly("sess_001", "user_001", "agent_req_002", 3L, "USER_MESSAGE",
                        Instant.parse("2026-07-07T08:00:03Z"), Instant.parse("2026-07-07T08:00:03Z"));
        assertThat(sqlExecutor.calls.getLast().sql()).contains("INSERT INTO agent_turns");
        assertThat(sqlExecutor.calls.getLast().args())
                .containsExactly("sess_001", 2L, 3L, 3L, "agent_req_002", "USER_MESSAGE", "user",
                        Instant.parse("2026-07-07T08:00:03Z"), Instant.parse("2026-07-07T08:00:03Z"));
    }

    @Test
    void recordsTranscriptToolEventIntoToolProjectionTable() {
        CapturingSqlExecutor sqlExecutor = new CapturingSqlExecutor();
        MysqlAgentSessionProjectionStore store = new MysqlAgentSessionProjectionStore(
                sqlExecutor,
                new ObjectMapper().findAndRegisterModules()
        );
        Instant occurredAt = Instant.parse("2026-07-07T08:00:04Z");

        store.recordTranscriptEntry(new AgentTranscriptEntry(
                "sess_001",
                4L,
                2L,
                1,
                "agent_req_002",
                "TOOL_RESULT",
                "tool",
                Map.of(
                        "tool_call_id", "call_001",
                        "tool_name", "recommend_candidates",
                        "status", "SUCCESS"
                ),
                occurredAt
        ));

        assertThat(sqlExecutor.calls).hasSize(3);
        assertThat(sqlExecutor.calls.getLast().sql()).contains("INSERT INTO agent_tool_calls");
        assertThat(sqlExecutor.calls.getLast().args()).containsExactly(
                "sess_001",
                "call_001",
                "agent_req_002",
                "recommend_candidates",
                "SUCCESS",
                "",
                "TOOL_RESULT",
                occurredAt,
                occurredAt
        );
    }

    @Test
    void recordsToolEventIntoSessionAndToolProjectionTables() {
        CapturingSqlExecutor sqlExecutor = new CapturingSqlExecutor();
        MysqlAgentSessionProjectionStore store = new MysqlAgentSessionProjectionStore(
                sqlExecutor,
                new ObjectMapper().findAndRegisterModules()
        );

        store.recordSessionEvent(new AgentSessionEvent(
                "evt_001",
                "sess_001",
                "agent_req_001",
                "TOOL_RESULT",
                1,
                "toolu_001",
                Map.of("tool_name", "search_products", "status", "SUCCESS"),
                "",
                "",
                Instant.parse("2026-07-07T08:00:01Z")
        ));

        assertThat(sqlExecutor.calls).hasSize(2);
        assertThat(sqlExecutor.calls.getFirst().sql()).contains("INSERT INTO agent_sessions");
        assertThat(sqlExecutor.calls.getFirst().args())
                .containsExactly("sess_001", "agent_req_001", "TOOL_RESULT", 1,
                        Instant.parse("2026-07-07T08:00:01Z"), Instant.parse("2026-07-07T08:00:01Z"));
        assertThat(sqlExecutor.calls.getLast().sql()).contains("INSERT INTO agent_tool_calls");
        assertThat(sqlExecutor.calls.getLast().args())
                .containsExactly("sess_001", "toolu_001", "agent_req_001", "search_products", "SUCCESS", "",
                        "TOOL_RESULT", Instant.parse("2026-07-07T08:00:01Z"),
                        Instant.parse("2026-07-07T08:00:01Z"));
    }

    @Test
    void recordsCheckpointIntoCheckpointProjectionTable() {
        CapturingSqlExecutor sqlExecutor = new CapturingSqlExecutor();
        MysqlAgentSessionProjectionStore store = new MysqlAgentSessionProjectionStore(
                sqlExecutor,
                new ObjectMapper().findAndRegisterModules()
        );

        store.recordCheckpoint(new AgentTranscriptCheckpoint(
                "cp_001",
                "sess_001",
                8L,
                List.of(Map.of("content", "summary")),
                List.of(Map.of("seq", 7L)),
                8,
                256,
                Instant.parse("2026-07-07T08:00:08Z")
        ));

        assertThat(sqlExecutor.calls).hasSize(2);
        assertThat(sqlExecutor.calls.getFirst().sql()).contains("INSERT INTO agent_checkpoints");
        assertThat(sqlExecutor.calls.getFirst().args().subList(0, 3))
                .containsExactly("sess_001", "cp_001", 8L);
        assertThat(sqlExecutor.calls.getLast().sql()).contains("UPDATE agent_sessions");
        assertThat(sqlExecutor.calls.getLast().args())
                .containsExactly("cp_001", 8L, Instant.parse("2026-07-07T08:00:08Z"), "sess_001");
    }

    private static final class CapturingSqlExecutor implements MysqlAgentSessionProjectionStore.SqlExecutor {

        private final List<SqlCall> calls = new ArrayList<>();

        @Override
        public void update(String sql, Object... args) {
            calls.add(new SqlCall(sql, Arrays.asList(args)));
        }
    }

    private record SqlCall(String sql, List<Object> args) {
    }
}
