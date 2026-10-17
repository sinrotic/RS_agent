package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentTraceReporterConfiguration;
import com.sinrotic.rs.agent.service.impl.HttpAgentTraceReporter;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;

class AgentTraceReporterConfigurationTest {

    @Test
    void enabledReporterIsClosedWithTheApplicationContext() {
        var reporter = new java.util.concurrent.atomic.AtomicReference<HttpAgentTraceReporter>();
        contextRunner.withBean(org.springframework.web.client.RestClient.Builder.class,
                        org.springframework.web.client.RestClient::builder)
                .withPropertyValues("rs.agent.trace.enabled=true")
                .run(context -> {
                    assertThat(context).hasSingleBean(AgentTraceReporter.class);
                    reporter.set((HttpAgentTraceReporter) context.getBean(AgentTraceReporter.class));
                });
        reporter.get().report(new com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO(
                "event", "session", "turn", "test", "", "", "", "", "", null,
                java.util.Map.of(), java.time.Instant.now()));
        assertThat(reporter.get().statistics().dropped()).isEqualTo(1);
    }

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withUserConfiguration(AgentTraceReporterConfiguration.class);

    @Test
    void createsNoopReporterWhenTraceIsDisabled() {
        contextRunner
                .withPropertyValues("rs.agent.trace.enabled=false")
                .run(context -> assertThat(context).hasSingleBean(AgentTraceReporter.class));
    }

    @Test
    void createsNoopReporterWhenTracePropertyIsMissing() {
        contextRunner.run(context -> assertThat(context).hasSingleBean(AgentTraceReporter.class));
    }
}
