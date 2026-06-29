package com.sinrotic.rs.agent.config;

import com.sinrotic.rs.agent.service.AgentTraceReporter;
import com.sinrotic.rs.agent.service.impl.HttpAgentTraceReporter;
import com.sinrotic.rs.agent.service.impl.NoopAgentTraceReporter;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

@Configuration
@EnableConfigurationProperties(AgentTraceReporterProperties.class)
public class AgentTraceReporterConfiguration {

    @Bean
    @ConditionalOnProperty(prefix = "rs.agent.trace", name = "enabled", havingValue = "false", matchIfMissing = true)
    public AgentTraceReporter noopAgentTraceReporter() {
        return new NoopAgentTraceReporter();
    }

    @Bean
    @ConditionalOnProperty(prefix = "rs.agent.trace", name = "enabled", havingValue = "true")
    public AgentTraceReporter httpAgentTraceReporter(
            RestClient.Builder restClientBuilder,
            AgentTraceReporterProperties properties
    ) {
        return new HttpAgentTraceReporter(restClientBuilder, properties);
    }
}
