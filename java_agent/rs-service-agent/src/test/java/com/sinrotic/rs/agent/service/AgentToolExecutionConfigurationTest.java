package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentToolExecutionConfiguration;
import com.sinrotic.rs.agent.service.impl.AgentCapabilityToolUseExecutor;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentCapabilityRegistry;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentToolResultStore;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class AgentToolExecutionConfigurationTest {

    @Test
    void exposesCapabilityGuardAsThePrimaryToolExecutor() {
        try (AnnotationConfigApplicationContext context = new AnnotationConfigApplicationContext()) {
            context.registerBean(AgentRuntimeConfigurationService.class, () -> new InMemoryAgentRuntimeConfigurationService());
            context.registerBean(AgentDelegateService.class, () -> (requestId, agentName, arguments) -> Map.of());
            context.registerBean(AgentToolResultStore.class, InMemoryAgentToolResultStore::new);
            context.registerBean(AgentCapabilityRegistry.class, () -> new InMemoryAgentCapabilityRegistry());
            context.register(AgentToolExecutionConfiguration.class);
            context.refresh();

            assertThat(context.getBean(AgentToolUseExecutor.class))
                    .isInstanceOf(AgentCapabilityToolUseExecutor.class);
        }
    }
}
