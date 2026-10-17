package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.memory.AgentMemoryIndexSnapshot;
import com.sinrotic.rs.agent.service.AgentMemoryIndexStore;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Optional;

public class MysqlAgentMemoryIndexStore implements AgentMemoryIndexStore {

    private final SqlExecutor sqlExecutor;

    public MysqlAgentMemoryIndexStore(SqlExecutor sqlExecutor) {
        this.sqlExecutor = sqlExecutor;
    }

    @Override
    public void save(AgentMemoryIndexSnapshot snapshot) {
        Instant updatedAt = snapshot.updatedAt() == null ? Instant.EPOCH : snapshot.updatedAt();
        sqlExecutor.update(
                """
                        INSERT INTO agent_memory_indexes (
                            tenant_id, profile_user_id, index_content, version, memory_count,
                            content_hash, updated_at, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON DUPLICATE KEY UPDATE
                            index_content = VALUES(index_content),
                            version = VALUES(version),
                            memory_count = VALUES(memory_count),
                            content_hash = VALUES(content_hash),
                            updated_at = VALUES(updated_at)
                        """,
                snapshot.tenantId(),
                snapshot.profileUserId(),
                snapshot.indexContent(),
                snapshot.version(),
                snapshot.memoryCount(),
                snapshot.contentHash(),
                updatedAt,
                updatedAt
        );
    }

    @Override
    public Optional<AgentMemoryIndexSnapshot> find(String tenantId, String profileUserId) {
        return sqlExecutor.queryMemoryIndex(
                """
                        SELECT tenant_id, profile_user_id, index_content, version, memory_count,
                               content_hash, updated_at
                        FROM agent_memory_indexes
                        WHERE tenant_id = ? AND profile_user_id = ?
                        """,
                tenantId,
                profileUserId
        );
    }

    public interface SqlExecutor {
        void update(String sql, Object... args);

        Optional<AgentMemoryIndexSnapshot> queryMemoryIndex(String sql, Object... args);
    }

    public static class DataSourceSqlExecutor implements SqlExecutor {

        private final DataSource dataSource;

        public DataSourceSqlExecutor(DataSource dataSource) {
            this.dataSource = dataSource;
        }

        @Override
        public void update(String sql, Object... args) {
            try (Connection connection = dataSource.getConnection();
                 PreparedStatement statement = connection.prepareStatement(sql)) {
                bind(statement, args);
                statement.executeUpdate();
            } catch (SQLException error) {
                throw new IllegalStateException("failed to update agent memory index", error);
            }
        }

        @Override
        public Optional<AgentMemoryIndexSnapshot> queryMemoryIndex(String sql, Object... args) {
            try (Connection connection = dataSource.getConnection();
                 PreparedStatement statement = connection.prepareStatement(sql)) {
                bind(statement, args);
                try (ResultSet resultSet = statement.executeQuery()) {
                    if (!resultSet.next()) {
                        return Optional.empty();
                    }
                    return Optional.of(new AgentMemoryIndexSnapshot(
                            resultSet.getString("tenant_id"),
                            resultSet.getString("profile_user_id"),
                            resultSet.getString("index_content"),
                            resultSet.getLong("version"),
                            resultSet.getInt("memory_count"),
                            resultSet.getString("content_hash"),
                            instant(resultSet.getTimestamp("updated_at"))
                    ));
                }
            } catch (SQLException error) {
                throw new IllegalStateException("failed to query agent memory index", error);
            }
        }

        private void bind(PreparedStatement statement, Object... args) throws SQLException {
            for (int index = 0; index < args.length; index++) {
                statement.setObject(index + 1, sqlValue(args[index]));
            }
        }

        private Object sqlValue(Object value) {
            if (value instanceof Instant instant) {
                return Timestamp.from(instant);
            }
            return value;
        }

        private Instant instant(Timestamp timestamp) {
            return timestamp == null ? Instant.EPOCH : timestamp.toInstant();
        }
    }
}
