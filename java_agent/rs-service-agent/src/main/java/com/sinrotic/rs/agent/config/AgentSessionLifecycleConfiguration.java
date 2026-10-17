package com.sinrotic.rs.agent.config;
import com.sinrotic.rs.agent.service.AgentSessionAdmissionClient;
import com.sinrotic.rs.agent.service.impl.HttpAgentSessionAdmissionClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.*;
@Configuration
public class AgentSessionLifecycleConfiguration {
    @Bean
    public AgentSessionAdmissionClient agentSessionAdmissionClient(
            @Value("${rs.agent.session-lifecycle.enabled:false}") boolean enabled,
            @Value("${rs.agent.session-lifecycle.user-base-url:http://rs-service-user:18101}") String userBaseUrl) {
        return enabled ? new HttpAgentSessionAdmissionClient(userBaseUrl) : request -> { };
    }
}
