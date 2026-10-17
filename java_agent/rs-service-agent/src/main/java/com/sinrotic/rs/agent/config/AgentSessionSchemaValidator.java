package com.sinrotic.rs.agent.config;

import com.datastax.oss.driver.api.core.CqlSession;
import com.datastax.oss.driver.api.core.cql.Row;
import com.datastax.oss.driver.api.core.cql.SimpleStatement;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;

public class AgentSessionSchemaValidator implements ApplicationRunner {

    private static final String COMPONENT = "agent-session";

    private final DataSource dataSource;

    private final CqlSession cqlSession;

    private final String expectedVersion;

    public AgentSessionSchemaValidator(DataSource dataSource, CqlSession cqlSession, String expectedVersion) {
        this.dataSource = dataSource;
        this.cqlSession = cqlSession;
        this.expectedVersion = expectedVersion;
    }

    @Override
    public void run(ApplicationArguments args) {
        validateMysql();
        validateScylla();
    }

    private void validateMysql() {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "SELECT version FROM agent_schema_version WHERE component = ?"
             )) {
            statement.setString(1, COMPONENT);
            try (ResultSet resultSet = statement.executeQuery()) {
                String actual = resultSet.next() ? resultSet.getString("version") : null;
                requireVersion(actual, "java_agent/sql/rs_service_agent_mysql_projection_schema.sql");
            }
        } catch (Exception error) {
            throw schemaFailure("java_agent/sql/rs_service_agent_mysql_projection_schema.sql", error);
        }
    }

    private void validateScylla() {
        try {
            Row row = cqlSession.execute(SimpleStatement.newInstance(
                    "SELECT version FROM agent_schema_version WHERE component = ?",
                    COMPONENT
            )).one();
            requireVersion(row == null ? null : row.getString("version"),
                    "java_agent/sql/rs_service_agent_scylla_session_schema.cql");
        } catch (Exception error) {
            throw schemaFailure("java_agent/sql/rs_service_agent_scylla_session_schema.cql", error);
        }
    }

    private void requireVersion(String actual, String migration) {
        if (!expectedVersion.equals(actual)) {
            throw schemaFailure(migration, null);
        }
    }

    private IllegalStateException schemaFailure(String migration, Exception cause) {
        String message = "Agent session schema must be migrated to " + expectedVersion + " using " + migration;
        return cause == null ? new IllegalStateException(message) : new IllegalStateException(message, cause);
    }
}
