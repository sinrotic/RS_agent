package com.sinrotic.rs.agent.config;

import com.sinrotic.rs.agent.service.AgentModelProviderHttpClient;
import com.sinrotic.rs.agent.service.AgentRecommendationClient;
import com.sinrotic.rs.agent.service.AgentRecommendationService;
import com.sinrotic.rs.agent.service.impl.HttpAgentRecommendationClient;
import com.sinrotic.rs.agent.service.impl.HttpAgentRecommendationService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRecommendationService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(AgentRecommendationProperties.class)
public class AgentRecommendationConfiguration {

    @Bean
    @ConditionalOnProperty(prefix = "rs.agent.recommendation", name = "type", havingValue = "http")
    public AgentRecommendationService httpAgentRecommendationService(
            AgentRecommendationProperties properties,
            AgentModelProviderHttpClient httpClient
    ) {
        AgentRecommendationClient client = new HttpAgentRecommendationClient(properties, httpClient);
        return new HttpAgentRecommendationService(client);
    }

    @Bean
    @ConditionalOnProperty(
            prefix = "rs.agent.recommendation",
            name = "type",
            havingValue = "memory",
            matchIfMissing = true
    )
    public AgentRecommendationService inMemoryAgentRecommendationService() {
        return new InMemoryAgentRecommendationService();
    }
}
