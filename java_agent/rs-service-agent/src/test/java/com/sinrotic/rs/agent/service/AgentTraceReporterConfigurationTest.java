package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentTraceReporterConfiguration;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;

class AgentTraceReporterConfigurationTest {

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
