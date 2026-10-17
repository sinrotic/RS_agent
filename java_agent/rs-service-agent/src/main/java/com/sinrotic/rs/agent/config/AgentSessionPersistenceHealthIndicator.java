package com.sinrotic.rs.agent.config;

import com.datastax.oss.driver.api.core.CqlSession;
import com.datastax.oss.driver.api.core.cql.SimpleStatement;
import org.springframework.boot.health.contributor.Health;
import org.springframework.boot.health.contributor.HealthIndicator;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import javax.sql.DataSource;
import java.sql.Connection;

@Component("agentSessionPersistence")
@ConditionalOnProperty(prefix = "rs.agent.session-persistence", name = "enabled", havingValue = "true")
public class AgentSessionPersistenceHealthIndicator implements HealthIndicator {

    private final DataSource dataSource;

    private final CqlSession cqlSession;

    private final AgentSessionPersistenceProperties properties;

    public AgentSessionPersistenceHealthIndicator(
            DataSource dataSource,
            CqlSession cqlSession,
            AgentSessionPersistenceProperties properties
    ) {
        this.dataSource = dataSource;
        this.cqlSession = cqlSession;
        this.properties = properties;
    }

    @Override
    public Health health() {
        try (Connection connection = dataSource.getConnection()) {
            if (!connection.isValid(2)) {
                return Health.down().withDetail("mysql", "connection validation failed").build();
            }
            cqlSession.execute(SimpleStatement.newInstance("SELECT release_version FROM system.local")).one();
            return Health.up()
                    .withDetail("mysql", "up")
                    .withDetail("scylla", "up")
                    .withDetail("schemaVersion", properties.getSchemaVersion())
                    .build();
        } catch (Exception error) {
            return Health.down(error).build();
        }
    }
}
