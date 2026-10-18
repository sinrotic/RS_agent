package com.sinrotic.rs.agent.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.config.AgentModelProviderConfiguration;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.service.impl.*;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.springframework.ai.model.chat.client.autoconfigure.ChatClientAutoConfiguration;
import org.springframework.ai.model.openai.autoconfigure.OpenAiChatAutoConfiguration;
import org.springframework.ai.model.tool.autoconfigure.ToolCallingAutoConfiguration;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.CancellationException;
import java.util.concurrent.atomic.*;
import static org.assertj.core.api.Assertions.*;

@Timeout(12)
class AgentModelBudgetHttpTest {
    private static final AgentChatRequestDTO REQUEST = new AgentChatRequestDTO("s","p","背包",1,Map.of("system_prompt","用中文回答"));
    @Test void startupRejectsHiddenSdkRetriesInsteadOfQuietlyOverspendingTheReservation() throws Exception {
        var server = server(200,new AtomicInteger(),new AtomicReference<>());
        try {
            runner(server).withPropertyValues("spring.ai.openai.chat.max-retries=3").run(ctx -> {
                assertThat(ctx).hasFailed();
                assertThat(ctx.getStartupFailure()).hasRootCauseInstanceOf(IllegalArgumentException.class)
                        .hasStackTraceContaining("request options do not override SDK retries");
            });
        } finally { server.stop(0); }
    }
    @Test void unsupportedHttpAdaptersCannotSilentlyDropTheBudgetFromEitherContextOverload() {
        var properties = new com.sinrotic.rs.agent.config.AgentModelProviderProperties();
        var settings = new com.sinrotic.rs.agent.config.AgentReasoningProperties(); settings.setDriftEnabled(false);
        AgentModelProviderHttpClient http = (url,body,accept) -> { throw new AssertionError("Unbudgeted network call"); };
        try (var policy = new AgentReasoningPolicy(settings)) {
            for (var client : List.<AgentModelStreamClient>of(new SelfHostedModelStreamClient(properties,http,policy),new PythonAgentApiModelStreamClient(properties,http,policy))) {
                var context = new AgentInterruptContext("t","s");
                try (var scope = policy.openTurn(context,REQUEST,e -> {},client)) {
                    assertThatThrownBy(() -> client.streamAssistantEvents("t",REQUEST,e -> {},context)).hasMessage("MODEL_BUDGET_ADAPTER_UNSUPPORTED");
                    assertThatThrownBy(() -> client.streamAssistantEvents("t",REQUEST,e -> {},context,ignored -> {})).hasMessage("MODEL_BUDGET_ADAPTER_UNSUPPORTED");
                }
            }
        }
    }
    @Test void actualWireUsesReservedOutputLimitAndFinalUsageSettlesTheSharedWorkerLedger() throws Exception {
        var calls = new AtomicInteger(); var wire = new AtomicReference<Map<?,?>>(); var server = server(200,calls,wire);
        try {
            runner(server).withPropertyValues("rs.agent.reasoning.max-model-calls=1").run(ctx -> {
                var client = ctx.getBean(AgentModelStreamClient.class); var turn = new AgentInterruptContext("t","s");
                var events = new ArrayList<AgentStreamEventVO>();
                try (var scope = client.reasoningPolicy().openTurn(turn,REQUEST,events::add,client)) {
                    var worker = turn.fork("worker");
                    client.streamAssistantEvents("t",REQUEST,e -> {},worker,ignored -> {});
                    assertThat(worker.budget()).isSameAs(turn.budget());
                    assertThat(turn.budget().snapshot()).containsEntry("settled_tokens",20L).containsEntry("held_tokens",0L);
                    assertThatThrownBy(() -> client.streamAssistantEvents("t",REQUEST,e -> {},turn.fork("summary"),ignored -> {}))
                            .hasMessage("MODEL_BUDGET_EXHAUSTED");
                    assertThat(calls.get()).isEqualTo(1);
                    assertThat(((Number)wire.get().get("max_tokens")).intValue()).isEqualTo(64);
                }
                assertThat(events).anySatisfy(e -> { assertThat(e.event()).isEqualTo("model_budget_completed"); assertThat(e.data()).containsEntry("closed",true); });
            });
        } finally { server.stop(0); }
    }
    @Test void exhaustedBudgetRejectsBeforeHttpAndTheLoopReportsAnExplicitInterruptedReason() throws Exception {
        var calls = new AtomicInteger(); var server = server(200,calls,new AtomicReference<>());
        try {
            runner(server).withPropertyValues("rs.agent.reasoning.max-tokens=1").run(ctx -> {
                var loop = new RsAgentLoop(new InMemoryAgentRuntimeConfigurationService(),e -> { throw new AssertionError(); },ctx.getBean(AgentModelStreamClient.class));
                var events = new ArrayList<AgentStreamEventVO>(); var result = loop.run(REQUEST,events::add);
                assertThat(result.finishReason()).isEqualTo(AgentFinishReason.INTERRUPTED);
                assertThat(events).anySatisfy(e -> { assertThat(e.event()).isEqualTo("interrupted"); assertThat(e.data()).containsEntry("reason","model_budget_exhausted"); });
                assertThat(calls.get()).isZero();
            });
        } finally { server.stop(0); }
    }
    @Test void anHttpFailureDoesNotHideSdkRetriesOrRefundUnknownProviderUsage() throws Exception {
        var calls = new AtomicInteger(); var server = server(503,calls,new AtomicReference<>());
        try {
            runner(server).run(ctx -> {
                var client = ctx.getBean(AgentModelStreamClient.class); var turn = new AgentInterruptContext("t","s");
                try (var scope = client.reasoningPolicy().openTurn(turn,REQUEST,e -> {},client)) {
                    assertThatThrownBy(() -> client.streamAssistantEvents("t",REQUEST,e -> {},turn,ignored -> {})).isInstanceOf(RuntimeException.class);
                    assertThat(calls.get()).isEqualTo(1);
                    assertThat(turn.budget().snapshot()).containsEntry("settled_tokens",0L).containsEntry("unknown_usage_calls",1L);
                    assertThat(((Number)turn.budget().snapshot().get("held_tokens")).longValue()).isPositive();
                }
            });
        } finally { server.stop(0); }
    }
    @Test void earlyConsumerCancellationKeepsTheReservationAndCannotBeCountedAsFree() throws Exception {
        var calls = new AtomicInteger(); var server = server(200,calls,new AtomicReference<>());
        try {
            runner(server).run(ctx -> {
                var client = ctx.getBean(AgentModelStreamClient.class); var turn = new AgentInterruptContext("t","s");
                try (var scope = client.reasoningPolicy().openTurn(turn,REQUEST,e -> {},client)) {
                    assertThatThrownBy(() -> client.streamAssistantEvents("t",REQUEST,e -> { if(e.isToken()) throw new CancellationException(); },turn,ignored -> {})).isInstanceOf(CancellationException.class);
                    assertThat(turn.budget().snapshot()).containsEntry("unknown_usage_calls",1L).containsEntry("settled_tokens",0L);
                }
            });
        } finally { server.stop(0); }
    }
    private ApplicationContextRunner runner(HttpServer server) {
        return new ApplicationContextRunner().withConfiguration(AutoConfigurations.of(OpenAiChatAutoConfiguration.class,ChatClientAutoConfiguration.class,ToolCallingAutoConfiguration.class))
                .withUserConfiguration(AgentModelProviderConfiguration.class).withPropertyValues(
                        "rs.agent.model-provider.type=spring_ai", "rs.agent.reasoning.drift-enabled=false", "spring.ai.openai.chat.max-retries=0",
                        "rs.agent.reasoning.max-output-tokens=64", "spring.ai.openai.base-url=http://127.0.0.1:"+server.getAddress().getPort(),
                        "spring.ai.openai.api-key=engineering-placeholder", "spring.ai.openai.chat.options.model=fixture-model",
                        "spring.ai.openai.chat.options.max-tokens=1024", "spring.ai.chat.client.tool-calling.enabled=false");
    }
    private HttpServer server(int status, AtomicInteger calls, AtomicReference<Map<?,?>> wire) throws Exception {
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1",0),0); var json = new ObjectMapper();
        server.createContext("/", exchange -> {
            wire.set(json.readValue(exchange.getRequestBody().readAllBytes(),Map.class)); calls.incrementAndGet();
            String text = "data: {\"id\":\"fixture\",\"object\":\"chat.completion.chunk\",\"model\":\"fixture-model\",\"choices\":[{\"index\":0,\"delta\":{\"content\":\"回答\"},\"finish_reason\":null}]}\n\n"
                    + "data: {\"id\":\"fixture\",\"object\":\"chat.completion.chunk\",\"model\":\"fixture-model\",\"choices\":[],\"usage\":{\"prompt_tokens\":15,\"completion_tokens\":5,\"total_tokens\":20}}\n\n"
                    + "data: [DONE]\n\n";
            byte[] body = (status == 200 ? text : "{\"error\":{\"message\":\"unavailable\",\"type\":\"server_error\"}}").getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type",status == 200 ? "text/event-stream" : "application/json");
            exchange.sendResponseHeaders(status,body.length); exchange.getResponseBody().write(body); exchange.close();
        }); server.start(); return server;
    }
}
