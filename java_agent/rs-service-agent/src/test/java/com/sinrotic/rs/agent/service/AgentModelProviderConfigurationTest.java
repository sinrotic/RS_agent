package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentModelProviderConfiguration;
import com.sinrotic.rs.agent.config.AgentModelProviderProperties;
import com.sinrotic.rs.agent.service.impl.PythonAgentApiModelStreamClient;
import com.sinrotic.rs.agent.service.impl.SelfHostedModelStreamClient;
import com.sinrotic.rs.agent.service.impl.SpringAiAgentModelStreamClient;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.assertThat;

class AgentModelProviderConfigurationTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withUserConfiguration(AgentModelProviderConfiguration.class)
            .withBean(AgentModelProviderHttpClient.class, () -> (url, payload, accept) -> "")
            .withBean(ChatModel.class, () -> org.mockito.Mockito.mock(ChatModel.class));

    @Test
    void defaultProviderUsesPythonApiClient() {
        contextRunner.run(context -> {
            assertThat(context).hasSingleBean(AgentModelStreamClient.class);
            assertThat(context.getBean(AgentModelStreamClient.class))
                    .isInstanceOf(PythonAgentApiModelStreamClient.class);
        });
    }

    @Test
    void selfHostedProviderUsesSelfHostedClient() {
        contextRunner
                .withPropertyValues("rs.agent.model-provider.type=self_hosted")
                .run(context -> {
                    assertThat(context).hasSingleBean(AgentModelStreamClient.class);
                    assertThat(context.getBean(AgentModelStreamClient.class))
                            .isInstanceOf(SelfHostedModelStreamClient.class);
                });
    }

    @Test
    void springAiProviderUsesSpringAiClient() {
        contextRunner
                .withPropertyValues("rs.agent.model-provider.type=spring_ai")
                .run(context -> {
                    assertThat(context).hasSingleBean(AgentModelStreamClient.class);
                    assertThat(context.getBean(AgentModelStreamClient.class))
                            .isInstanceOf(SpringAiAgentModelStreamClient.class);
                });
    }

    @Test
    void pythonApiClientReadsTokenDeltasFromPythonStreamResponse() {
        AgentModelProviderProperties properties = new AgentModelProviderProperties();
        properties.pythonApi().setBaseUrl("http://python-agent");
        properties.pythonApi().setStreamPath("/chat/stream");
        AgentModelProviderHttpClient httpClient = new AgentModelProviderHttpClient() {
            @Override
            public String postJson(String url, String payload, String accept) {
                throw new AssertionError("python api provider must stream model events");
            }

            @Override
            public void streamJson(String url, String payload, String accept, Consumer<String> lineConsumer) {
                lineConsumer.accept("data: {\"type\":\"token\",\"delta\":\"Hello \"}");
                lineConsumer.accept("data: {\"type\":\"token\",\"delta\":\"world\"}");
                lineConsumer.accept("data: {\"type\":\"done\",\"done\":true}");
            }
        };
        PythonAgentApiModelStreamClient client = new PythonAgentApiModelStreamClient(properties, httpClient);

        List<String> deltas = client.streamAssistantDeltas(
                "agent_req_001",
                new com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO(
                        "sess_001",
                        "A1XYZ",
                        "Find a backpack",
                        5,
                        java.util.Map.of()
                )
        );

        assertThat(deltas).containsExactly("Hello ", "world");
    }

    @Test
    void pythonApiClientConsumesEventsThroughStreamingHttpClient() {
        AgentModelProviderProperties properties = new AgentModelProviderProperties();
        properties.pythonApi().setBaseUrl("http://python-agent");
        properties.pythonApi().setStreamPath("/chat/stream");
        AtomicBoolean streamingCalled = new AtomicBoolean(false);
        AgentModelProviderHttpClient httpClient = new AgentModelProviderHttpClient() {
            @Override
            public String postJson(String url, String payload, String accept) {
                throw new AssertionError("python api provider must stream model events");
            }

            @Override
            public void streamJson(String url, String payload, String accept, Consumer<String> lineConsumer) {
                streamingCalled.set(true);
                lineConsumer.accept("data: {\"type\":\"token\",\"delta\":\"Hello \"}");
                lineConsumer.accept("data: {\"type\":\"tool_use\",\"tool_name\":\"recommend_candidates\",\"arguments\":{\"limit\":2}}");
                lineConsumer.accept("data: {\"type\":\"token\",\"delta\":\"world\"}");
                lineConsumer.accept("data: {\"type\":\"done\",\"done\":true}");
            }
        };
        PythonAgentApiModelStreamClient client = new PythonAgentApiModelStreamClient(properties, httpClient);
        List<com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent> events = new java.util.ArrayList<>();

        client.streamAssistantEvents(
                "agent_req_001",
                new com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO(
                        "sess_001",
                        "A1XYZ",
                        "Find a backpack",
                        5,
                        java.util.Map.of()
                ),
                events::add
        );

        assertThat(streamingCalled).isTrue();
        assertThat(events).extracting(com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent::type)
                .containsExactly("token", "tool_use", "token", "done");
    }

    @Test
    void selfHostedClientReadsTokenDeltasFromSseResponse() {
        AgentModelProviderProperties properties = new AgentModelProviderProperties();
        properties.selfHosted().setBaseUrl("http://model-service");
        properties.selfHosted().setStreamPath("/internal/model/chat/stream");
        AgentModelProviderHttpClient httpClient = (url, payload, accept) -> """
                event: token
                data: {"event":"token","request_id":"agent_req_001","delta":"A ","done":false}

                event: token
                data: {"event":"token","request_id":"agent_req_001","delta":"B","done":false}

                event: done
                data: {"event":"done","request_id":"agent_req_001","delta":"","done":true}

                """;
        SelfHostedModelStreamClient client = new SelfHostedModelStreamClient(properties, httpClient);

        List<String> deltas = client.streamAssistantDeltas(
                "agent_req_001",
                new com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO(
                        "sess_001",
                        "A1XYZ",
                        "Find a backpack",
                        5,
                        java.util.Map.of()
                )
        );

        assertThat(deltas).containsExactly("A ", "B");
    }

    @Test
    void selfHostedClientConsumesSseLinesThroughStreamingHttpClient() {
        AgentModelProviderProperties properties = new AgentModelProviderProperties();
        properties.selfHosted().setBaseUrl("http://model-service");
        properties.selfHosted().setStreamPath("/internal/model/chat/stream");
        AtomicBoolean streamingCalled = new AtomicBoolean(false);
        AgentModelProviderHttpClient httpClient = new AgentModelProviderHttpClient() {
            @Override
            public String postJson(String url, String payload, String accept) {
                throw new AssertionError("self-hosted streaming client must not buffer full response");
            }

            @Override
            public void streamJson(String url, String payload, String accept, Consumer<String> lineConsumer) {
                streamingCalled.set(true);
                lineConsumer.accept("event: token");
                lineConsumer.accept("data: {\"event\":\"token\",\"request_id\":\"agent_req_001\",\"delta\":\"A \",\"done\":false}");
                lineConsumer.accept("");
                lineConsumer.accept("event: done");
                lineConsumer.accept("data: {\"event\":\"done\",\"request_id\":\"agent_req_001\",\"delta\":\"\",\"done\":true}");
            }
        };
        SelfHostedModelStreamClient client = new SelfHostedModelStreamClient(properties, httpClient);

        List<String> deltas = client.streamAssistantDeltas(
                "agent_req_001",
                new com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO(
                        "sess_001",
                        "A1XYZ",
                        "Find a backpack",
                        5,
                        java.util.Map.of()
                )
        );

        assertThat(streamingCalled).isTrue();
        assertThat(deltas).containsExactly("A ");
    }
}
