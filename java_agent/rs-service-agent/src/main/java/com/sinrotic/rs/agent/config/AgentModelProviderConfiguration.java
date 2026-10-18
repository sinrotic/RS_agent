package com.sinrotic.rs.agent.config;

import com.sinrotic.rs.agent.service.AgentModelProviderHttpClient;
import com.sinrotic.rs.agent.service.AgentModelStreamClient;
import com.sinrotic.rs.agent.service.AgentDelegateService;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.AgentToolResultStore;
import com.sinrotic.rs.agent.service.impl.HttpAgentDelegateService;
import com.sinrotic.rs.agent.service.impl.JavaNetAgentModelProviderHttpClient;
import com.sinrotic.rs.agent.service.impl.PythonAgentApiModelStreamClient;
import com.sinrotic.rs.agent.service.impl.SelfHostedModelStreamClient;
import com.sinrotic.rs.agent.service.impl.SpringAiAgentModelStreamClient;
import com.sinrotic.rs.agent.service.impl.OpenAiModelStreamResources;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.openai.http.okhttp.OpenAiHttpClientBuilderCustomizer;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties({AgentModelProviderProperties.class, AgentDelegateProperties.class, AgentReasoningProperties.class})
public class AgentModelProviderConfiguration {

    @Bean
    public com.sinrotic.rs.agent.service.impl.AgentReasoningPolicy agentReasoningPolicy(AgentReasoningProperties properties,
            ObjectProvider<org.springframework.ai.model.openai.autoconfigure.OpenAiChatProperties> chatProperties) {
        var chat = chatProperties.getIfAvailable();
        if (properties.isBudgetEnabled() && chat != null && chat.getMaxRetries() != 0)
            throw new IllegalArgumentException("Budget enforcement requires spring.ai.openai.chat.max-retries=0; request options do not override SDK retries");
        return new com.sinrotic.rs.agent.service.impl.AgentReasoningPolicy(properties);
    }

    @Bean
    @ConditionalOnProperty(prefix = "rs.agent.model-provider", name = "type", havingValue = "spring_ai")
    public OpenAiModelStreamResources openAiModelStreamResources() {
        return new OpenAiModelStreamResources();
    }

    @Bean
    @ConditionalOnProperty(prefix = "rs.agent.model-provider", name = "type", havingValue = "spring_ai")
    public OpenAiHttpClientBuilderCustomizer agentModelStreamHttpCancellation(OpenAiModelStreamResources resources) {
        return builder -> builder.interceptor(resources);
    }

    @Bean
    @ConditionalOnMissingBean
    public AgentModelProviderHttpClient agentModelProviderHttpClient() {
        return new JavaNetAgentModelProviderHttpClient();
    }

    @Bean
    @ConditionalOnMissingBean
    public AgentDelegateService agentDelegateService(
            AgentDelegateProperties properties,
            AgentModelProviderHttpClient httpClient
    ) {
        return new HttpAgentDelegateService(properties, httpClient);
    }

    @Bean
    @ConditionalOnProperty(
            prefix = "rs.agent.model-provider",
            name = "type",
            havingValue = "python_api",
            matchIfMissing = true
    )
    public AgentModelStreamClient pythonAgentApiModelStreamClient(
            AgentModelProviderProperties properties,
            AgentModelProviderHttpClient httpClient,
            com.sinrotic.rs.agent.service.impl.AgentReasoningPolicy policy
    ) {
        return new PythonAgentApiModelStreamClient(properties, httpClient, policy);
    }

    @Bean
    @ConditionalOnProperty(
            prefix = "rs.agent.model-provider",
            name = "type",
            havingValue = "self_hosted"
    )
    public AgentModelStreamClient selfHostedModelStreamClient(
            AgentModelProviderProperties properties,
            AgentModelProviderHttpClient httpClient,
            com.sinrotic.rs.agent.service.impl.AgentReasoningPolicy policy
    ) {
        return new SelfHostedModelStreamClient(properties, httpClient, policy);
    }

    @Bean
    @ConditionalOnMissingBean(AgentModelStreamClient.class)
    @ConditionalOnProperty(
            prefix = "rs.agent.model-provider",
            name = "type",
            havingValue = "spring_ai"
    )
    public AgentModelStreamClient springAiAgentModelStreamClientFromChatModel(
            ChatModel chatModel,
            AgentModelProviderProperties properties,
            ObjectProvider<AgentRuntimeConfigurationService> runtimeConfigurationServiceProvider,
            ObjectProvider<AgentToolResultStore> toolResultStoreProvider,
            OpenAiModelStreamResources streamResources,
            com.sinrotic.rs.agent.service.impl.AgentReasoningPolicy policy
    ) {
        return new SpringAiAgentModelStreamClient(
                chatModel,
                runtimeConfigurationServiceProvider.getIfAvailable(),
                toolResultStoreProvider.getIfAvailable(),
                properties.isConstrainedDecodingEnabled(),
                streamResources,
                properties.getFinalAnswerMaxTokens(),
                properties.isCompactToolSchemasEnabled(), policy
        );
    }
}
