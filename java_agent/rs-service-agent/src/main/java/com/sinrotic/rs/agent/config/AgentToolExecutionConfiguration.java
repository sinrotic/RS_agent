package com.sinrotic.rs.agent.config;

import com.sinrotic.rs.agent.service.AgentCapabilityRegistry;
import com.sinrotic.rs.agent.service.AgentDelegateService;
import com.sinrotic.rs.agent.service.AgentExecutionLimiter;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.AgentToolResultStore;
import com.sinrotic.rs.agent.service.AgentToolUseExecutor;
import com.sinrotic.rs.agent.service.impl.AgentCapabilityToolUseExecutor;
import com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor;
import com.sinrotic.rs.agent.service.impl.GovernedAgentToolUseExecutor;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(AgentToolGovernanceProperties.class)
public class AgentToolExecutionConfiguration {

    @Bean(destroyMethod = "close")
    public VirtualThreadAgentToolUseExecutor virtualThreadAgentToolUseExecutor(
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentDelegateService agentDelegateService,
            AgentToolResultStore toolResultStore,
            AgentExecutionLimiter executionLimiter
    ) {
        return new VirtualThreadAgentToolUseExecutor(
                runtimeConfigurationService,
                agentDelegateService,
                toolResultStore,
                executionLimiter
        );
    }

    @Bean
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

    @Bean(destroyMethod = "close")
    @Primary
    public GovernedAgentToolUseExecutor governedAgentToolUseExecutor(
            @org.springframework.beans.factory.annotation.Qualifier("agentCapabilityToolUseExecutor") AgentToolUseExecutor delegate,
            AgentToolGovernanceProperties properties, AgentRuntimeConfigurationService runtime,
            AgentCapabilityRegistry registry) {
        return new GovernedAgentToolUseExecutor(delegate, properties, runtime, registry);
    }
}
