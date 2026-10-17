package com.sinrotic.rs.agent.config;

import com.sinrotic.rs.agent.service.AgentTraceReporter;
import com.sinrotic.rs.agent.service.impl.HttpAgentTraceReporter;
import com.sinrotic.rs.agent.service.impl.NoopAgentTraceReporter;
import com.sinrotic.rs.agent.service.impl.CompositeAgentTraceReporter;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

@Configuration
@EnableConfigurationProperties(AgentTraceReporterProperties.class)
public class AgentTraceReporterConfiguration {

    @Bean(destroyMethod = "close")
    public AgentTraceReporter agentTraceReporter(
            ObjectProvider<RestClient.Builder> builders,
            AgentTraceReporterProperties properties
    ) {
        var targets = new java.util.ArrayList<AgentTraceReporter>();
        try {
            if (properties.isEnabled()) targets.add(new HttpAgentTraceReporter(builders.getIfAvailable(RestClient::builder), properties));
            if (properties.getOtlp().isEnabled()) targets.add(HttpAgentTraceReporter.otlp(builders.getIfAvailable(RestClient::builder), properties));
        } catch (RuntimeException invalidConfig) {
            targets.forEach(AgentTraceReporter::close);
            throw invalidConfig;
        }
        return targets.isEmpty() ? new NoopAgentTraceReporter() : targets.size() == 1 ? targets.getFirst()
                : new CompositeAgentTraceReporter(targets);
    }
}
