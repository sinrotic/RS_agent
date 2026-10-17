package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.MysqlAgentSessionProjectionStore;
import org.h2.jdbcx.JdbcDataSource;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.*;

class AgentProjectionTransactionTest {
    private JdbcDataSource dataSource;
    private JdbcTemplate jdbc;
    private MysqlAgentSessionProjectionStore.DataSourceSqlExecutor executor;

    @BeforeEach
    void setUp() {
        dataSource = spy(new JdbcDataSource());
        dataSource.setURL("jdbc:h2:mem:" + UUID.randomUUID() + ";MODE=MySQL;DB_CLOSE_DELAY=-1");
        jdbc = new JdbcTemplate(dataSource);
        jdbc.execute("""
                CREATE TABLE agent_sessions (
                  session_id VARCHAR PRIMARY KEY, user_id VARCHAR, last_request_id VARCHAR,
                  last_seq BIGINT, last_entry_type VARCHAR, last_entry_at TIMESTAMP, updated_at TIMESTAMP)
                """);
        jdbc.execute("""
                CREATE TABLE agent_turns (
                  session_id VARCHAR, turn_no BIGINT CHECK (turn_no > 0), first_seq BIGINT, last_seq BIGINT,
                  request_id VARCHAR, last_entry_type VARCHAR, last_role VARCHAR,
                  updated_at TIMESTAMP, created_at TIMESTAMP, PRIMARY KEY (session_id, turn_no))
                """);
        executor = new MysqlAgentSessionProjectionStore.DataSourceSqlExecutor(dataSource);
        clearInvocations(dataSource);
    }

    @Test
    void relatedWritesShareOneConnectionAndCommitTogether() throws Exception {
        project(1);
        verify(dataSource, times(1)).getConnection();
        assertThat(jdbc.queryForObject("SELECT last_seq FROM agent_sessions", Long.class)).isEqualTo(1L);
        assertThat(jdbc.queryForObject("SELECT last_seq FROM agent_turns", Long.class)).isEqualTo(1L);
    }

    @Test
    void failedTurnProjectionRollsBackSessionProjection() {
        assertThatThrownBy(() -> project(0)).isInstanceOf(RuntimeException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_sessions", Integer.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_turns", Integer.class)).isZero();
        project(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_sessions", Integer.class)).isEqualTo(1);
    }

    private void project(long turnNo) {
        executor.inTransaction(sql -> {
            sql.update("INSERT INTO agent_sessions (session_id, last_seq) VALUES (?, ?)", "session-1", 1L);
            sql.update("INSERT INTO agent_turns (session_id, turn_no, last_seq) VALUES (?, ?, ?)", "session-1", turnNo, 1L);
        });
    }
}
