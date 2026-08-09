package com.sinrotic.rs.agent.config;

import com.sinrotic.rs.agent.service.AgentCapabilityRegistry;
import com.sinrotic.rs.agent.service.AgentDelegateService;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.AgentToolResultStore;
import com.sinrotic.rs.agent.service.AgentToolUseExecutor;
import com.sinrotic.rs.agent.service.impl.AgentCapabilityToolUseExecutor;
import com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;

@Configuration(proxyBeanMethods = false)
public class AgentToolExecutionConfiguration {

    @Bean(destroyMethod = "close")
    public VirtualThreadAgentToolUseExecutor virtualThreadAgentToolUseExecutor(
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentDelegateService agentDelegateService,
            AgentToolResultStore toolResultStore
    ) {
        return new VirtualThreadAgentToolUseExecutor(
                runtimeConfigurationService,
                agentDelegateService,
                toolResultStore
        );
    }

    @Bean
    @Primary
    public AgentToolUseExecutor agentCapabilityToolUseExecutor(
            VirtualThreadAgentToolUseExecutor delegate,
            AgentCapabilityRegistry capabilityRegistry,
            AgentRuntimeConfigurationService runtimeConfigurationService
    ) {
        return new AgentCapabilityToolUseExecutor(
                delegate,
                capabilityRegistry,
                runtimeConfigurationService
        );
    }
}
