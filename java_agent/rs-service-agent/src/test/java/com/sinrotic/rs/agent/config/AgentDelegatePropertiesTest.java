package com.sinrotic.rs.agent.config;

import com.sinrotic.rs.agent.service.AgentModelProviderHttpClient;
import com.sinrotic.rs.agent.service.impl.HttpAgentDelegateService;
import org.junit.jupiter.api.Test;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.context.annotation.Configuration;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

class AgentDelegatePropertiesTest {
    @Test
    void boundEndpointActuallyReceivesTheRagDelegation() {
        new ApplicationContextRunner().withUserConfiguration(Binding.class).withPropertyValues(
                "rs.agent.delegate.rag-agent.base-url=http://127.0.0.1:18213",
                "rs.agent.delegate.rag-agent.support-path=/test/rag/support").run(context -> {
            var properties = context.getBean(AgentDelegateProperties.class);
            assertThat(properties.ragAgent().getBaseUrl()).isEqualTo("http://127.0.0.1:18213");
            assertThat(properties.ragAgent().getSupportPath()).isEqualTo("/test/rag/support");
            var http = mock(AgentModelProviderHttpClient.class);
            when(http.postJson(anyString(), anyString(), anyString())).thenReturn("{\"status\":\"SUCCESS\"}");
            var delegate = new HttpAgentDelegateService(properties, http);
            assertThat(delegate.callAgent("request", "rag_agent", Map.of("query", "推荐鼠标")))
                    .containsEntry("status", "SUCCESS");
            verify(http).postJson(eq("http://127.0.0.1:18213/test/rag/support"), anyString(), eq("application/json"));
        });
    }

    @Configuration(proxyBeanMethods = false)
    @EnableConfigurationProperties(AgentDelegateProperties.class)
    static class Binding { }
}
