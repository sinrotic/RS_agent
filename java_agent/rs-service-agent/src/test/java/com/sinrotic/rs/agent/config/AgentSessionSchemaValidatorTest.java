package com.sinrotic.rs.agent.config;

import com.datastax.oss.driver.api.core.CqlSession;
import com.datastax.oss.driver.api.core.cql.Row;
import org.junit.jupiter.api.Test;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AgentSessionSchemaValidatorTest {

    @Test
    void acceptsMatchingMysqlAndScyllaSchemaVersions() throws Exception {
        DataSource dataSource = mysqlSchemaVersion("agent_session_v1");
        CqlSession cqlSession = scyllaSchemaVersion("agent_session_v1");

        new AgentSessionSchemaValidator(dataSource, cqlSession, "agent_session_v1").run(null);
    }

    @Test
    void failsFastWhenMysqlSchemaIsOutdated() throws Exception {
        DataSource dataSource = mysqlSchemaVersion("agent_session_v0");
        CqlSession cqlSession = scyllaSchemaVersion("agent_session_v1");

        assertThatThrownBy(() -> new AgentSessionSchemaValidator(dataSource, cqlSession, "agent_session_v1").run(null))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("rs_service_agent_mysql_projection_schema.sql")
                .hasMessageContaining("agent_session_v1");
    }

    private DataSource mysqlSchemaVersion(String version) throws Exception {
        DataSource dataSource = mock(DataSource.class);
        Connection connection = mock(Connection.class);
        PreparedStatement statement = mock(PreparedStatement.class);
        ResultSet resultSet = mock(ResultSet.class);
        when(dataSource.getConnection()).thenReturn(connection);
        when(connection.prepareStatement(any())).thenReturn(statement);
        when(statement.executeQuery()).thenReturn(resultSet);
        when(resultSet.next()).thenReturn(true);
        when(resultSet.getString("version")).thenReturn(version);
        return dataSource;
    }

    private CqlSession scyllaSchemaVersion(String version) {
        CqlSession session = mock(CqlSession.class);
        com.datastax.oss.driver.api.core.cql.ResultSet resultSet =
                mock(com.datastax.oss.driver.api.core.cql.ResultSet.class);
        Row row = mock(Row.class);
        when(session.execute(any(com.datastax.oss.driver.api.core.cql.Statement.class))).thenReturn(resultSet);
        when(resultSet.one()).thenReturn(row);
        when(row.getString("version")).thenReturn(version);
        return session;
    }
}
