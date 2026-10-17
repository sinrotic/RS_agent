package com.sinrotic.rs.agent.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.config.AgentModelProviderConfiguration;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.session.AgentToolResultLines;
import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentToolResultStore;
import com.sinrotic.rs.agent.service.impl.SpringAiAgentModelStreamClient;
import com.sinrotic.rs.agent.service.impl.RsAgentLoop;
import com.sinrotic.rs.agent.service.impl.AgentFinishReason;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentInterrupter;
import com.sinrotic.rs.agent.service.impl.NoopAgentLoopHookDispatcher;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeToolUpsertDTO;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.ai.model.chat.client.autoconfigure.ChatClientAutoConfiguration;
import org.springframework.ai.model.openai.autoconfigure.OpenAiChatAutoConfiguration;
import org.springframework.ai.model.tool.autoconfigure.ToolCallingAutoConfiguration;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SpringAiAgentModelStreamClientSmokeTest {

    private static final Pattern TOOL_RESULT_REF_PATTERN = Pattern.compile("agent:result:tool_results:[^\\\\\"]+");

    @ParameterizedTest
    @CsvSource({"true,false", "false,false", "true,true"})
    void actualLoopKeepsLoadedSkillEvidenceAndPreservesCustomLoopBehavior(boolean compact, boolean customLoop) throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        var requests = new ArrayList<String>();
        var mapper = new ObjectMapper();
        server.createContext("/", exchange -> {
            requests.add(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            String name = requests.size() == 1 ? "load_skill" : "emit_final_answer";
            Map<String, Object> arguments = requests.size() == 1
                    ? Map.of("skill_name", "explicit-need-recommendation")
                    : Map.of("blocks", List.of(Map.of("type", "text", "content", "完整模型推荐回答")));
            var function = Map.of("name", name, "arguments", mapper.writeValueAsString(arguments));
            var call = Map.of("index", 0, "id", "call_" + requests.size(), "type", "function", "function", function);
            var choice = Map.of("index", 0, "delta", Map.of("tool_calls", List.of(call)), "finish_reason", "tool_calls");
            byte[] response = ("data: " + mapper.writeValueAsString(Map.of("id", "mock", "object", "chat.completion.chunk",
                    "created", 1, "model", "mock-model", "choices", List.of(choice))) + "\n\ndata: [DONE]\n\n")
                    .getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response); exchange.close();
        });
        server.start();
        try {
            streamingProvider(server.getAddress().getPort())
                    .withPropertyValues("rs.agent.model-provider.compact-tool-schemas-enabled=" + compact)
                    .run(context -> {
                        var runtime = context.getBean(AgentRuntimeConfigurationService.class);
                        var executor = new com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor(runtime);
                        var model = context.getBean(AgentModelStreamClient.class);
                        RsAgentLoop loop = customLoop
                                ? new RsAgentLoop(runtime, executor, model, new NoopAgentLoopHookDispatcher(), new InMemoryAgentInterrupter()) { }
                                : new RsAgentLoop(runtime, executor, model, new NoopAgentLoopHookDispatcher(), new InMemoryAgentInterrupter());
                        var result = loop.run(new AgentChatRequestDTO("skill-wire", "user", "推荐鼠标", 5, Map.of()), event -> {});
                        assertThat(result.finishReason()).isEqualTo(AgentFinishReason.FINAL_ANSWER);
                        assertThat(result.assistantMessage()).isEqualTo("完整模型推荐回答");
                        assertThat(requests).hasSize(2);
                        assertThat(requests.get(1)).contains("explicit-need-recommendation");
                        assertThat(requests.get(1)).doesNotContain("__agent_allow_loaded_skill_reuse");
                        try {
                            var request = mapper.readTree(requests.get(1));
                            var names = findTool(request, "load_skill").path("function").path("parameters")
                                    .path("properties").path("skill_name").path("enum");
                            if (compact && !customLoop) {
                                assertThat(names).isNotEmpty();
                                assertThat(names.toString()).doesNotContain("explicit-need-recommendation");
                            } else assertThat(names.isMissingNode()).isTrue();
                        } catch (IOException error) { throw new IllegalStateException(error); }
                    });
        } finally { server.stop(0); }
    }

    @Test
    void consumerFailureClosesTheActualHttpRequestWithoutChangingConfiguredHeaders() throws Exception {
        try (var server = new LongStreamServer()) {
            streamingProvider(server.port()).run(context -> {
                var runtime = context.getBean(AgentRuntimeConfigurationService.class);
                for (var tool : runtime.tools()) {
                    runtime.upsertTool(tool.name(), new AgentRuntimeToolUpsertDTO(
                            tool.service(), tool.description(), false, tool.parametersSchema()));
                }
                var failure = new IllegalStateException("consumer disconnected");
                assertThatThrownBy(() -> context.getBean(AgentModelStreamClient.class).streamAssistantEvents(
                        "http-disconnect", new AgentChatRequestDTO("http-disconnect", "test-user", "回复一句话", 1, Map.of()), event -> {
                            throw failure;
                        })).isSameAs(failure);
                assertThat(server.disconnected.await(2, TimeUnit.SECONDS)).isTrue();
                assertThat(server.providerHeader.get()).isEqualTo("kept");
                assertThat(server.scopeHeader.get()).isNull();
            });
        }
    }

    @Test
    void userInterruptClosesHttpAndFinishesTheAgentWhileNoModelEventIsReady() throws Exception {
        try (var server = new LongStreamServer()) {
            streamingProvider(server.port()).run(context -> {
                var interrupter = new InMemoryAgentInterrupter();
                var loop = new RsAgentLoop(context.getBean(AgentRuntimeConfigurationService.class), event -> {
                    throw new AssertionError("interrupted model must not call tools");
                }, context.getBean(AgentModelStreamClient.class), new NoopAgentLoopHookDispatcher(), interrupter);
                var executor = Executors.newVirtualThreadPerTaskExecutor();
                try {
                    var result = executor.submit(() -> loop.run(new AgentChatRequestDTO(
                            "http-interrupt", "test-user", "回复一句话", 1, Map.of("__agent_turn_request_id", "http-interrupt")), event -> {}));
                    assertThat(server.connected.await(2, TimeUnit.SECONDS)).isTrue();
                    assertThat(interrupter.interruptOwned("http-interrupt", "test-user", "user_interrupt")).isTrue();
                    assertThat(result.get(2, TimeUnit.SECONDS).finishReason()).isEqualTo(AgentFinishReason.INTERRUPTED);
                    assertThat(server.disconnected.await(2, TimeUnit.SECONDS)).isTrue();
                } finally {
                    executor.shutdownNow();
                }
            });
        }
    }

    @Test
    void interruptingOneSessionLeavesTheOtherModelRequestRunning() throws Exception {
        try (var server = new LongStreamServer(2)) {
            streamingProvider(server.port()).run(context -> {
                var interrupter = new InMemoryAgentInterrupter();
                var loop = new RsAgentLoop(context.getBean(AgentRuntimeConfigurationService.class), event -> {
                    throw new AssertionError("unfinished model must not execute tools");
                }, context.getBean(AgentModelStreamClient.class), new NoopAgentLoopHookDispatcher(), interrupter);
                var executor = Executors.newVirtualThreadPerTaskExecutor();
                try {
                    var first = executor.submit(() -> loop.run(interruptibleRequest("first"), event -> {}));
                    var second = executor.submit(() -> loop.run(interruptibleRequest("second"), event -> {}));
                    assertThat(server.connected.await(2, TimeUnit.SECONDS)).isTrue();
                    assertThat(interrupter.interruptOwned("first", "test-user", "user_interrupt")).isTrue();
                    assertThat(first.get(2, TimeUnit.SECONDS).finishReason()).isEqualTo(AgentFinishReason.INTERRUPTED);
                    assertThat(server.disconnected.await(2, TimeUnit.SECONDS)).isTrue();
                    assertThat(second.isDone()).isFalse();
                    assertThat(server.disconnectCount.get()).isEqualTo(1);
                    assertThat(interrupter.interruptOwned("second", "test-user", "user_interrupt")).isTrue();
                    assertThat(second.get(2, TimeUnit.SECONDS).finishReason()).isEqualTo(AgentFinishReason.INTERRUPTED);
                    assertThat(server.allDisconnected.await(2, TimeUnit.SECONDS)).isTrue();
                } finally {
                    executor.shutdownNow();
                }
            });
        }
    }

    private static AgentChatRequestDTO interruptibleRequest(String id) {
        return new AgentChatRequestDTO(id, "test-user", "回复一句话", 1, Map.of("__agent_turn_request_id", id));
    }

    private static ApplicationContextRunner streamingProvider(int port) {
        return new ApplicationContextRunner()
                .withConfiguration(AutoConfigurations.of(ToolCallingAutoConfiguration.class,
                        OpenAiChatAutoConfiguration.class, ChatClientAutoConfiguration.class))
                .withUserConfiguration(AgentModelProviderConfiguration.class, InMemoryAgentRuntimeConfigurationService.class)
                .withPropertyValues("rs.agent.model-provider.type=spring_ai", "rs.agent.model-provider.constrained-decoding-enabled=true",
                        "spring.ai.model.chat=openai", "spring.ai.chat.client.tool-calling.enabled=false",
                        "spring.ai.openai.base-url=http://127.0.0.1:" + port,
                        "spring.ai.openai.api-key=test-key", "spring.ai.openai.chat.options.model=mock-model",
                        "spring.ai.openai.custom-headers[X-provider-test]=kept");
    }

    private static class LongStreamServer implements AutoCloseable {
        private final HttpServer server;
        private final ExecutorService executor = Executors.newVirtualThreadPerTaskExecutor();
        private final CountDownLatch connected;
        private final CountDownLatch disconnected = new CountDownLatch(1);
        private final CountDownLatch allDisconnected;
        private final AtomicInteger disconnectCount = new AtomicInteger();
        private final AtomicReference<String> providerHeader = new AtomicReference<>();
        private final AtomicReference<String> scopeHeader = new AtomicReference<>();

        private LongStreamServer() throws IOException {
            this(1);
        }

        private LongStreamServer(int connections) throws IOException {
            connected = new CountDownLatch(connections);
            allDisconnected = new CountDownLatch(connections);
            server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.setExecutor(executor);
            server.createContext("/", exchange -> {
                exchange.getRequestBody().readAllBytes();
                providerHeader.set(exchange.getRequestHeaders().getFirst("X-provider-test"));
                scopeHeader.set(exchange.getRequestHeaders().getFirst("X-RS-Agent-Stream-Scope"));
                exchange.getResponseHeaders().add("Content-Type", "text/event-stream");
                exchange.sendResponseHeaders(200, 0);
                connected.countDown();
                try {
                    exchange.getResponseBody().write("""
                            data: {"id":"chatcmpl_tail","object":"chat.completion.chunk","created":1,"model":"mock","choices":[{"index":0,"delta":{"content":"first"},"finish_reason":null}]}

                            """.getBytes(StandardCharsets.UTF_8));
                    exchange.getResponseBody().flush();
                    byte[] tail = (":" + "x".repeat(8192) + "\n\n").getBytes(StandardCharsets.UTF_8);
                    long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
                    while (System.nanoTime() < deadline) {
                        exchange.getResponseBody().write(tail);
                        exchange.getResponseBody().flush();
                        Thread.sleep(5);
                    }
                } catch (IOException error) {
                    disconnectCount.incrementAndGet();
                    disconnected.countDown();
                    allDisconnected.countDown();
                } catch (InterruptedException error) {
                    Thread.currentThread().interrupt();
                } finally {
                    exchange.close();
                }
            });
            server.start();
        }

        private int port() {
            return server.getAddress().getPort();
        }

        @Override
        public void close() {
            server.stop(0);
            executor.shutdownNow();
        }
    }

    @ParameterizedTest
    @CsvSource({"0,0,false", "1,4096,false", "2,0,false", "2,4096,false", "2,64,false",
            "0,4096,true", "1,4096,true", "2,4096,true", "1,64,true"})
    void springAiProviderStreamsFromOpenAiCompatibleApi(int mode, int finalBudget, boolean compact) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicReference<String> requestBody = new AtomicReference<>("");
        server.createContext("/v1/chat/completions", exchange -> {
            requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] response = structuredToolSse().getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.createContext("/chat/completions", exchange -> {
            requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] response = structuredToolSse().getBytes(StandardCharsets.UTF_8);
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
                            "rs.agent.model-provider.constrained-decoding-enabled=" + (mode > 0),
                            "rs.agent.model-provider.final-answer-max-tokens=" + finalBudget,
                            "rs.agent.model-provider.compact-tool-schemas-enabled=" + compact,
                            "spring.ai.model.chat=openai",
                            "spring.ai.chat.client.tool-calling.enabled=false",
                            "spring.ai.openai.base-url=http://127.0.0.1:" + port,
                            "spring.ai.openai.api-key=test-key",
                            "spring.ai.openai.chat.options.model=mock-model",
                            "spring.ai.openai.chat.options.temperature=0.25",
                            "spring.ai.openai.chat.options.max-tokens=128",
                            "spring.ai.openai.chat.options.tool-choice=required",
                            "spring.ai.openai.chat.options.parallel-tool-calls=true"
                    )
                    .run(context -> {
                        assertThat(context).hasSingleBean(AgentModelStreamClient.class);
                        assertThat(context.getBean(AgentModelStreamClient.class))
                                .isInstanceOf(SpringAiAgentModelStreamClient.class);

                        List<AgentModelStreamEvent> events = new ArrayList<>();
                        var chatRequest = new AgentChatRequestDTO(
                                "sess_spring_ai", "A1XYZ", "ping", 1,
                                Map.of(
                                        "system_prompt", "answer briefly",
                                        "final_answer_only", mode == 2,
                                        "runtime_context_messages", List.of("custom-runtime-marker"),
                                        "tool_results", List.of(Map.of("status", "SUCCEEDED", "evidence", "dynamic-evidence-marker")),
                                        "custom_business_context", "opaque-context-marker",
                                        "available_tools", List.of(Map.of(
                                                "name", "redundant_text_tool",
                                                "description", "This tool listing must not be serialized into the system prompt."
                                        ))
                                )
                        );
                        context.getBean(AgentModelStreamClient.class).streamAssistantEvents(
                                "agent_req_spring_ai",
                                chatRequest,
                                events::add
                        );

                        String coldRequestBody = requestBody.get();
                        List<AgentModelStreamEvent> repeatedEvents = new ArrayList<>();
                        context.getBean(AgentModelStreamClient.class).streamAssistantEvents(
                                "agent_req_spring_ai_repeat", chatRequest, repeatedEvents::add);
                        assertThat(repeatedEvents).isEqualTo(events);

                        assertThat(events).extracting(AgentModelStreamEvent::type)
                                .containsExactly("tool_use", "done");
                        assertThat(events.getFirst().toolName()).isEqualTo("emit_final_answer");
                        assertThat(events.getFirst().arguments()).containsKey("blocks");
                        assertThat(requestBody.get())
                                .contains("\"tools\"")
                                .contains("\"emit_final_answer\"");
                        if (mode != 2) {
                            assertThat(requestBody.get()).contains("\"load_skill\"").contains("\"call_agent\"");
                        }
                        assertThat(requestBody.get())
                                .doesNotContain("available_tools")
                                .doesNotContain("redundant_text_tool")
                                .contains("custom-runtime-marker", "dynamic-evidence-marker", "opaque-context-marker");
                        try {
                            JsonNode request = new ObjectMapper()
                                    .enable(com.fasterxml.jackson.core.JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
                                    .readTree(requestBody.get());
                            assertThat(request).isEqualTo(new ObjectMapper().readTree(coldRequestBody));
                            assertThat(request.path("model").asText()).isEqualTo("mock-model");
                            assertThat(request.path("temperature").asDouble()).isEqualTo(0.25);
                            int expectedBudget = mode == 2 && finalBudget > 0 ? Math.max(128, finalBudget) : 128;
                            assertThat(request.path(request.has("max_tokens") ? "max_tokens" : "max_completion_tokens").asInt()).isEqualTo(expectedBudget);
                            if (mode == 2) {
                                assertThat(request.path("tools")).hasSize(1);
                                assertThat(request.path("tool_choice").path("function").path("name").asText())
                                        .isEqualTo("emit_final_answer");
                            } else {
                                assertThat(request.path("tool_choice").asText()).isEqualTo("required");
                            }
                            assertThat(request.path("parallel_tool_calls").asBoolean()).isEqualTo(mode == 0);
                            if (mode > 0) {
                                assertThat(request.path("chat_template_kwargs").path("enable_thinking").asBoolean(true)).isFalse();
                                for (JsonNode tool : request.path("tools")) {
                                    assertThat(tool.path("function").path("strict").asBoolean()).isTrue();
                                    assertThat(tool.path("function").path("parameters").has("strict")).isFalse();
                                }
                            }
                            JsonNode finalAnswerTool = findTool(request, "emit_final_answer");
                            JsonNode parameters = finalAnswerTool.path("function").path("parameters");
                            assertThat(parameters.path("additionalProperties").asBoolean()).isFalse();
                            JsonNode blockSchema = parameters.path("properties").path("blocks").path("items");
                            if (mode > 0 && compact) {
                                assertThat(blockSchema.path("anyOf")).hasSize(6);
                                assertThat(blockSchema.path("anyOf").get(5).path("properties").has("messages")).isTrue();
                            } else {
                                assertThat(blockSchema.path("additionalProperties").asBoolean()).isFalse();
                                assertThat(blockSchema.path("required")).hasSize(6);
                                assertThat(blockSchema.path("properties").has("messages")).isTrue();
                            }
                        } catch (IOException error) {
                            throw new IllegalStateException(error);
                        }
                    });
        } finally {
            server.stop(0);
        }
    }

    @Test
    void springAiProviderExternalizesAggregateToolResultBudgetBeforePrompt() throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicReference<String> requestBody = new AtomicReference<>("");
        server.createContext("/v1/chat/completions", exchange -> {
            requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] response = structuredToolSse().getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.createContext("/chat/completions", exchange -> {
            requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] response = structuredToolSse().getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        try {
            int port = server.getAddress().getPort();
            String largeEvidence = "largest-evidence-" + "x".repeat(1_700);
            new ApplicationContextRunner()
                    .withConfiguration(AutoConfigurations.of(
                            ToolCallingAutoConfiguration.class,
                            OpenAiChatAutoConfiguration.class,
                            ChatClientAutoConfiguration.class
                    ))
                    .withUserConfiguration(
                            AgentModelProviderConfiguration.class,
                            InMemoryAgentRuntimeConfigurationService.class,
                            InMemoryAgentToolResultStore.class
                    )
                    .withPropertyValues(
                            "rs.agent.model-provider.type=spring_ai",
                            "spring.ai.model.chat=openai",
                            "spring.ai.chat.client.tool-calling.enabled=false",
                            "spring.ai.openai.base-url=http://127.0.0.1:" + port,
                            "spring.ai.openai.api-key=test-key",
                            "spring.ai.openai.chat.options.model=mock-model",
                            "spring.ai.openai.chat.options.tool-choice=required",
                            "spring.ai.openai.chat.options.parallel-tool-calls=true"
                    )
                    .run(context -> {
                        List<String> deltas = context.getBean(AgentModelStreamClient.class)
                                .streamAssistantDeltas(
                                        "agent_req_spring_ai_budget",
                                        new AgentChatRequestDTO(
                                                "sess_spring_ai_budget",
                                                "A1XYZ",
                                                "summarize evidence",
                                                1,
                                                Map.of(
                                                        "system_prompt", "answer briefly",
                                                        "tool_results", List.of(
                                                                Map.of(
                                                                        "tool_call_id", "toolu_budget_large",
                                                                        "tool_name", "rag_support",
                                                                        "service", "rs-service-agent",
                                                                        "status", "SUCCESS",
                                                                        "metadata", Map.of("evidence", largeEvidence)
                                                                ),
                                                                Map.of(
                                                                        "tool_call_id", "toolu_budget_small_a",
                                                                        "tool_name", "rag_support",
                                                                        "service", "rs-service-agent",
                                                                        "status", "SUCCESS",
                                                                        "metadata", Map.of("evidence", "small-a-" + "a".repeat(900))
                                                                ),
                                                                Map.of(
                                                                        "tool_call_id", "toolu_budget_small_b",
                                                                        "tool_name", "rag_support",
                                                                        "service", "rs-service-agent",
                                                                        "status", "SUCCESS",
                                                                        "metadata", Map.of("evidence", "small-b-" + "b".repeat(900))
                                                                )
                                                        )
                                                )
                                        )
                                );

                        assertThat(deltas).isEmpty();
                        assertThat(requestBody.get())
                                .contains("result_externalized")
                                .contains("read_tool_result_lines")
                                .doesNotContain(largeEvidence);

                        Matcher matcher = TOOL_RESULT_REF_PATTERN.matcher(requestBody.get());
                        assertThat(matcher.find()).isTrue();
                        AgentToolResultLines stored = context.getBean(AgentToolResultStore.class)
                                .readLines(matcher.group(), 0, 200);
                        assertThat(stored.lines()).anySatisfy(line -> assertThat(line).contains("largest-evidence-"));
                    });
        } finally {
            server.stop(0);
        }
    }

    private static JsonNode findTool(JsonNode request, String toolName) {
        for (JsonNode tool : request.path("tools")) {
            if (toolName.equals(tool.path("function").path("name").asText())) {
                return tool;
            }
        }
        throw new IllegalArgumentException("missing tool in request: " + toolName);
    }

    private static String structuredToolSse() {
        return """
                data: {"id":"chatcmpl_mock","object":"chat.completion.chunk","created":1,"model":"mock","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_final","type":"function","function":{"name":"emit_final_answer","arguments":"{\\\"blocks\\\":[{\\\"type\\\":\\\"text\\\",\\\"content\\\":\\\"结构化输出通过\\\",\\\"card_set_id\\\":null,\\\"item_ids\\\":null,\\\"layout\\\":null}]}"}}]},"finish_reason":null}]}

                data: {"id":"chatcmpl_mock","object":"chat.completion.chunk","created":1,"model":"mock","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}

                data: [DONE]

                """;
    }
}
