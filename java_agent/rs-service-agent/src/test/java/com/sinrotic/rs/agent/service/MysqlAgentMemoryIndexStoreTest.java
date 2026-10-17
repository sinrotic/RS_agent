package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.memory.AgentMemoryIndexSnapshot;
import com.sinrotic.rs.agent.service.impl.MysqlAgentMemoryIndexStore;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

class MysqlAgentMemoryIndexStoreTest {

    @Test
    void savesUserMemoryIndexSnapshotWithoutPerItemMetaTable() {
        CapturingSqlExecutor sqlExecutor = new CapturingSqlExecutor();
        MysqlAgentMemoryIndexStore store = new MysqlAgentMemoryIndexStore(sqlExecutor);

        store.save(new AgentMemoryIndexSnapshot(
                "tenant_001",
                "profile_user_001",
                "- [budget](mem_001) - user prefers good value",
                7L,
                1,
                "hash_001",
                Instant.parse("2026-07-09T02:00:00Z")
        ));

        assertThat(sqlExecutor.updates).hasSize(1);
        assertThat(sqlExecutor.updates.getFirst().sql()).contains("INSERT INTO agent_memory_indexes");
        assertThat(sqlExecutor.updates.getFirst().sql()).doesNotContain("memory_item_meta");
        assertThat(sqlExecutor.updates.getFirst().args()).containsExactly(
                "tenant_001",
                "profile_user_001",
                "- [budget](mem_001) - user prefers good value",
                7L,
                1,
                "hash_001",
                Instant.parse("2026-07-09T02:00:00Z"),
                Instant.parse("2026-07-09T02:00:00Z")
        );
    }

    @Test
    void loadsUserMemoryIndexSnapshotByTenantAndProfileUser() {
        CapturingSqlExecutor sqlExecutor = new CapturingSqlExecutor();
        sqlExecutor.queryResult = Optional.of(new AgentMemoryIndexSnapshot(
                "tenant_001",
                "profile_user_001",
                "- [budget](mem_001) - user prefers good value",
                7L,
                1,
                "hash_001",
                Instant.parse("2026-07-09T02:00:00Z")
        ));
        MysqlAgentMemoryIndexStore store = new MysqlAgentMemoryIndexStore(sqlExecutor);

        Optional<AgentMemoryIndexSnapshot> snapshot = store.find("tenant_001", "profile_user_001");

        assertThat(snapshot).hasValueSatisfying(value -> {
            assertThat(value.indexContent()).contains("(mem_001)");
            assertThat(value.version()).isEqualTo(7L);
        });
        assertThat(sqlExecutor.queries).hasSize(1);
        assertThat(sqlExecutor.queries.getFirst().sql()).contains("FROM agent_memory_indexes");
        assertThat(sqlExecutor.queries.getFirst().args()).containsExactly("tenant_001", "profile_user_001");
    }

    private static final class CapturingSqlExecutor implements MysqlAgentMemoryIndexStore.SqlExecutor {

        private final List<SqlCall> updates = new ArrayList<>();

        private final List<SqlCall> queries = new ArrayList<>();

        private Optional<AgentMemoryIndexSnapshot> queryResult = Optional.empty();

        @Override
        public void update(String sql, Object... args) {
            updates.add(new SqlCall(sql, Arrays.asList(args)));
        }

        @Override
        public Optional<AgentMemoryIndexSnapshot> queryMemoryIndex(String sql, Object... args) {
            queries.add(new SqlCall(sql, Arrays.asList(args)));
            return queryResult;
        }
    }

    private record SqlCall(String sql, List<Object> args) {
    }
}
