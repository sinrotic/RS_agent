package com.sinrotic.rs.agent.config;

import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(AgentTemplateProperties.class)
public class AgentTemplateConfiguration {

    @Bean
    @ConditionalOnMissingBean
    public AgentRuntimeConfigurationService agentRuntimeConfigurationService(AgentTemplateProperties properties) {
        return new InMemoryAgentRuntimeConfigurationService(properties);
    }
}
