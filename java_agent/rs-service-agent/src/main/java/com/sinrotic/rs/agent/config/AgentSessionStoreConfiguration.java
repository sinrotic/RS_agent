package com.sinrotic.rs.agent.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.service.AgentHotSessionStore;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentHotSessionStore;
import com.sinrotic.rs.agent.service.impl.RedisAgentHotSessionStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.core.StringRedisTemplate;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(AgentSessionStoreProperties.class)
public class AgentSessionStoreConfiguration {

    @Bean
    @ConditionalOnProperty(prefix = "rs.agent.session-store", name = "type", havingValue = "redis")
    public AgentHotSessionStore redisAgentHotSessionStore(
            StringRedisTemplate redisTemplate,
            ObjectMapper objectMapper,
            AgentSessionStoreProperties properties
    ) {
        return new RedisAgentHotSessionStore(redisTemplate, objectMapper, properties);
    }

    @Bean
    @ConditionalOnProperty(
            prefix = "rs.agent.session-store",
            name = "type",
            havingValue = "memory",
            matchIfMissing = true
    )
    public AgentHotSessionStore inMemoryAgentHotSessionStore() {
        return new InMemoryAgentHotSessionStore();
    }
}
