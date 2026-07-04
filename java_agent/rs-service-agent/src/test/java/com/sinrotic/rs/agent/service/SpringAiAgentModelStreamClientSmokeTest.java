package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentModelProviderConfiguration;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.SpringAiAgentModelStreamClient;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.ai.model.chat.client.autoconfigure.ChatClientAutoConfiguration;
import org.springframework.ai.model.openai.autoconfigure.OpenAiChatAutoConfiguration;
import org.springframework.ai.model.tool.autoconfigure.ToolCallingAutoConfiguration;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

class SpringAiAgentModelStreamClientSmokeTest {

    @Test
    void springAiProviderStreamsFromOpenAiCompatibleApi() throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicReference<String> requestBody = new AtomicReference<>("");
        server.createContext("/v1/chat/completions", exchange -> {
            requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] response = ("""
                    data: {"id":"chatcmpl_mock","object":"chat.completion.chunk","created":1,"model":"mock","choices":[{"index":0,"delta":{"content":"hello "},"finish_reason":null}]}

                    data: {"id":"chatcmpl_mock","object":"chat.completion.chunk","created":1,"model":"mock","choices":[{"index":0,"delta":{"content":"spring ai"},"finish_reason":null}]}

                    data: {"id":"chatcmpl_mock","object":"chat.completion.chunk","created":1,"model":"mock","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

                    data: [DONE]

                    """).getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.createContext("/chat/completions", exchange -> {
            requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] response = ("""
                    data: {"id":"chatcmpl_mock","object":"chat.completion.chunk","created":1,"model":"mock","choices":[{"index":0,"delta":{"content":"hello "},"finish_reason":null}]}

                    data: {"id":"chatcmpl_mock","object":"chat.completion.chunk","created":1,"model":"mock","choices":[{"index":0,"delta":{"content":"spring ai"},"finish_reason":null}]}

                    data: {"id":"chatcmpl_mock","object":"chat.completion.chunk","created":1,"model":"mock","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

                    data: [DONE]

                    """).getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        try {
            int port = server.getAddress().getPort();
            new ApplicationContextRunner()
                    .withConfiguration(AutoConfigurations.of(
                            ToolCallingAutoConfiguration.class,
                            OpenAiChatAutoConfiguration.class,
                            ChatClientAutoConfiguration.class
                    ))
                    .withUserConfiguration(
                            AgentModelProviderConfiguration.class,
                            InMemoryAgentRuntimeConfigurationService.class
                    )
                    .withPropertyValues(
                            "rs.agent.model-provider.type=spring_ai",
                            "spring.ai.model.chat=openai",
                            "spring.ai.openai.base-url=http://127.0.0.1:" + port,
                            "spring.ai.openai.api-key=test-key",
                            "spring.ai.openai.chat.options.model=mock-model"
                    )
                    .run(context -> {
                        assertThat(context).hasSingleBean(AgentModelStreamClient.class);
                        assertThat(context.getBean(AgentModelStreamClient.class))
                                .isInstanceOf(SpringAiAgentModelStreamClient.class);

                        List<String> deltas = context.getBean(AgentModelStreamClient.class)
                                .streamAssistantDeltas(
                                        "agent_req_spring_ai",
                                        new AgentChatRequestDTO(
                                                "sess_spring_ai",
                                                "A1XYZ",
                                                "ping",
                                                1,
                                                Map.of("system_prompt", "answer briefly")
                                        )
                                );

                        assertThat(deltas).containsExactly("hello ", "spring ai");
                        assertThat(requestBody.get())
                                .contains("\"tools\"")
                                .contains("\"load_skill\"")
                                .contains("\"call_agent\"")
                                .contains("\"emit_final_answer\"");
                    });
        } finally {
            server.stop(0);
        }
    }
}
