package com.sinrotic.rs.agent.config;

import com.sinrotic.rs.agent.service.impl.RedisAgentSessionTtlExpirationListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.listener.PatternTopic;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;

@Configuration
@ConditionalOnBean(RedisAgentSessionTtlExpirationListener.class)
public class AgentSessionExpirationConfiguration {

    @Bean
    public RedisMessageListenerContainer agentSessionExpirationRedisContainer(
            RedisConnectionFactory connectionFactory,
            RedisAgentSessionTtlExpirationListener listener
    ) {
        RedisMessageListenerContainer container = new RedisMessageListenerContainer();
        container.setConnectionFactory(connectionFactory);
        container.addMessageListener(listener, new PatternTopic("__keyevent@*__:expired"));
        return container;
    }
}
