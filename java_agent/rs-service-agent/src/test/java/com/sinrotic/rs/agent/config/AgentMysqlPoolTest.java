package com.sinrotic.rs.agent.config;

import org.h2.jdbc.JdbcConnection;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AgentMysqlPoolTest {
    @Test
    void closingLogicalConnectionReusesPhysicalConnectionAndPoolCanClose() throws Exception {
        var properties = new AgentSessionPersistenceProperties();
        properties.getMysql().setJdbcUrl("jdbc:h2:mem:agent-pool");
        properties.getMysql().setUsername("sa");
        properties.getMysql().setPassword("");
        properties.getMysql().setMaximumPoolSize(1);
        properties.getMysql().setMinimumIdle(1);
        var pool = new AgentSessionPersistenceConfiguration().agentSessionMysqlDataSource(properties);
        try (pool) {
            JdbcConnection physical;
            try (var first = pool.getConnection()) {
                physical = first.unwrap(JdbcConnection.class);
            }
            try (var second = pool.getConnection()) {
                assertThat(second.unwrap(JdbcConnection.class)).isSameAs(physical);
                assertThat(second.getAutoCommit()).isTrue();
            }
            assertThat(pool.getHikariPoolMXBean().getTotalConnections()).isEqualTo(1);
        }
        assertThat(pool.isClosed()).isTrue();
    }
}
