package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentCapabilityConfiguration;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;

import static org.assertj.core.api.Assertions.assertThat;

class AgentCapabilityConfigurationTest {

    @Test
    void exposesCapabilityRegistryAsAnApplicationBean() {
        try (AnnotationConfigApplicationContext context = new AnnotationConfigApplicationContext(
                AgentCapabilityConfiguration.class
        )) {
            assertThat(context.getBean(AgentCapabilityRegistry.class)).isNotNull();
        }
    }
}
