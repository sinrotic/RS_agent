package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentToolExecutionConfiguration;
import com.sinrotic.rs.agent.config.AgentExecutionProperties;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentCapabilityRegistry;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentToolResultStore;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class AgentToolExecutionConfigurationTest {

    @Test
    void exposesGovernanceWrappingTheCapabilityGuardAsThePrimaryToolExecutor() {
        try (AnnotationConfigApplicationContext context = new AnnotationConfigApplicationContext()) {
            context.registerBean(AgentRuntimeConfigurationService.class, () -> new InMemoryAgentRuntimeConfigurationService());
            context.registerBean(AgentDelegateService.class, () -> (requestId, agentName, arguments) -> Map.of());
            context.registerBean(AgentToolResultStore.class, InMemoryAgentToolResultStore::new);
            context.registerBean(AgentCapabilityRegistry.class, () -> new InMemoryAgentCapabilityRegistry());
            context.registerBean(AgentExecutionLimiter.class, () -> new AgentExecutionLimiter(new AgentExecutionProperties()));
            context.register(AgentToolExecutionConfiguration.class);
            context.refresh();

            assertThat(context.getBean(AgentToolUseExecutor.class))
                    .isInstanceOf(com.sinrotic.rs.agent.service.impl.GovernedAgentToolUseExecutor.class);
        }
    }
}
