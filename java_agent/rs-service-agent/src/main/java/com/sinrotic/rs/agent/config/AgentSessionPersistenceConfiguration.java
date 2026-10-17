package com.sinrotic.rs.agent.config;

import com.datastax.oss.driver.api.core.CqlSession;
import com.zaxxer.hikari.HikariDataSource;
import com.sinrotic.rs.agent.service.AgentMemoryIndexStore;
import com.sinrotic.rs.agent.service.AgentSessionProjectionStore;
import com.sinrotic.rs.agent.service.AgentTranscriptCheckpointStore;
import com.sinrotic.rs.agent.service.AgentTranscriptEntryStore;
import com.sinrotic.rs.agent.service.AgentTranscriptRecoveryService;
import com.sinrotic.rs.agent.service.impl.DefaultAgentTranscriptRecoveryService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentTranscriptCheckpointStore;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentTranscriptEntryStore;
import com.sinrotic.rs.agent.service.impl.MysqlAgentMemoryIndexStore;
import com.sinrotic.rs.agent.service.impl.MysqlAgentSessionProjectionStore;
import com.sinrotic.rs.agent.service.impl.NoopAgentSessionProjectionStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import javax.sql.DataSource;
import java.net.InetSocketAddress;

@Configuration
@EnableConfigurationProperties(AgentSessionPersistenceProperties.class)
public class AgentSessionPersistenceConfiguration {

    @Bean
    @ConditionalOnMissingBean
    public AgentTranscriptEntryStore inMemoryAgentTranscriptEntryStore() {
        return new InMemoryAgentTranscriptEntryStore();
    }

    @Bean
    @ConditionalOnMissingBean
    public AgentTranscriptCheckpointStore inMemoryAgentTranscriptCheckpointStore() {
        return new InMemoryAgentTranscriptCheckpointStore();
    }

    @Bean
    @ConditionalOnMissingBean
    public AgentTranscriptRecoveryService agentTranscriptRecoveryService(
            AgentTranscriptCheckpointStore checkpointStore,
            AgentTranscriptEntryStore entryStore
    ) {
        return new DefaultAgentTranscriptRecoveryService(checkpointStore, entryStore);
    }

    @Bean
    @ConditionalOnProperty(
            prefix = "rs.agent.session-persistence",
            name = "enabled",
            havingValue = "false",
            matchIfMissing = true
    )
    public AgentSessionProjectionStore noopAgentSessionProjectionStore() {
        return new NoopAgentSessionProjectionStore();
    }

    @Bean
    @ConditionalOnMissingBean
    @ConditionalOnProperty(prefix = "rs.agent.session-persistence", name = "enabled", havingValue = "true")
    public CqlSession agentSessionCqlSession(AgentSessionPersistenceProperties properties) {
        AgentSessionPersistenceProperties.Scylla scylla = properties.getScylla();
        return CqlSession.builder()
                .addContactPoint(new InetSocketAddress(scylla.getHost(), scylla.getPort()))
                .withLocalDatacenter(scylla.getLocalDatacenter())
                .withKeyspace(scylla.getKeyspace())
                .build();
    }

    @Bean(destroyMethod = "close")
    @ConditionalOnMissingBean(DataSource.class)
    @ConditionalOnProperty(prefix = "rs.agent.session-persistence", name = "enabled", havingValue = "true")
    public HikariDataSource agentSessionMysqlDataSource(AgentSessionPersistenceProperties properties) {
        AgentSessionPersistenceProperties.Mysql mysql = properties.getMysql();
        HikariDataSource dataSource = new HikariDataSource();
        dataSource.setPoolName("agent-session-mysql");
        dataSource.setJdbcUrl(mysql.getJdbcUrl());
        dataSource.setUsername(mysql.getUsername());
        dataSource.setPassword(mysql.getPassword());
        dataSource.setMaximumPoolSize(mysql.getMaximumPoolSize());
        dataSource.setMinimumIdle(mysql.getMinimumIdle());
        dataSource.setConnectionTimeout(mysql.getConnectionTimeoutMs());
        return dataSource;
    }

    @Bean
    @ConditionalOnProperty(prefix = "rs.agent.session-persistence", name = "enabled", havingValue = "true")
    public AgentSessionSchemaValidator agentSessionSchemaValidator(
            DataSource dataSource,
            CqlSession cqlSession,
            AgentSessionPersistenceProperties properties
    ) {
        return new AgentSessionSchemaValidator(dataSource, cqlSession, properties.getSchemaVersion());
    }

    @Bean
    @ConditionalOnMissingBean(AgentSessionProjectionStore.class)
    @ConditionalOnProperty(prefix = "rs.agent.session-persistence", name = "enabled", havingValue = "true")
    public AgentSessionProjectionStore agentSessionProjectionStore(DataSource dataSource) {
        return new MysqlAgentSessionProjectionStore(
                new MysqlAgentSessionProjectionStore.DataSourceSqlExecutor(dataSource),
                MysqlAgentSessionProjectionStore.defaultObjectMapper()
        );
    }

    @Bean
    @ConditionalOnMissingBean(AgentMemoryIndexStore.class)
    @ConditionalOnProperty(prefix = "rs.agent.session-persistence", name = "enabled", havingValue = "true")
    public AgentMemoryIndexStore agentMemoryIndexStore(DataSource dataSource) {
        return new MysqlAgentMemoryIndexStore(
                new MysqlAgentMemoryIndexStore.DataSourceSqlExecutor(dataSource)
        );
    }
}
