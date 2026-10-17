package com.sinrotic.rs.agent.config;

import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.AgentDependencyReadiness;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(AgentTemplateProperties.class)
public class AgentTemplateConfiguration {

    @Bean
    @ConditionalOnMissingBean
    public AgentRuntimeConfigurationService agentRuntimeConfigurationService(AgentTemplateProperties properties,
            @Value("${rs.agent.delegate.rag-agent.base-url:${rs.recommend.base-url:http://rs-service-recommend:18103}}") String recommendUrl,
            @Value("${rs.agent.recommendation.type:memory}") String recommendationType) {
        return new InMemoryAgentRuntimeConfigurationService(properties,
                new AgentDependencyReadiness(recommendUrl, "http".equals(recommendationType)));
    }
}
