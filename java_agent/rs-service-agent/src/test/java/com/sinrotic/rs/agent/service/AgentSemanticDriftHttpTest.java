package com.sinrotic.rs.agent.service;

import com.fasterxml.jackson.databind.*;
import com.sinrotic.rs.agent.config.AgentModelProviderConfiguration;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.service.impl.*;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.ai.model.chat.client.autoconfigure.ChatClientAutoConfiguration;
import org.springframework.ai.model.openai.autoconfigure.OpenAiChatAutoConfiguration;
import org.springframework.ai.model.tool.autoconfigure.ToolCallingAutoConfiguration;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.atomic.*;
import static org.assertj.core.api.Assertions.*;

@Timeout(12)
class AgentSemanticDriftHttpTest {
    private static final AgentChatRequestDTO REQUEST = new AgentChatRequestDTO("s","p","挑旅行背包",1,Map.of());
    @ParameterizedTest @ValueSource(strings={"DRIFT","ALIGNED","invalid"})
    void actualModelReviewUsesNoToolsAndSettlesAgainstTheSameTurnBudget(String reply) throws Exception {
        var wire = new AtomicReference<JsonNode>(); var count = new AtomicInteger(); var server = server(reply,wire,count);
        try {
            runner(server).run(ctx -> {
                var model = ctx.getBean(AgentModelStreamClient.class); var context = new AgentInterruptContext("t","s");
                var events = new ArrayList<AgentStreamEventVO>();
                try (var turn = model.reasoningPolicy().openTurn(context,REQUEST,events::add,model)) {
                    var decision = turn.beforeTool(AgentModelStreamEvent.toolUse("recommend_candidates",Map.of("query","帐篷面料")));
                    assertThat(decision.status()).isEqualTo(reply.equals("invalid") ? "UNKNOWN" : reply);
                    assertThat(decision.blocked()).isEqualTo(!reply.equals("ALIGNED"));
                    assertThat(wire.get().path("tool_choice").asText()).isEqualTo("none");
                    assertThat(wire.get().has("tools")).isFalse();
                    assertThat(wire.get().path("max_tokens").asInt()).isEqualTo(256);
                    assertThat(wire.get().path("messages").get(0).path("content").asText()).contains("语义相关性检查器");
                    assertThat(context.budget().snapshot()).containsEntry("settled_tokens",20L).containsEntry("held_tokens",0L);
                    model.streamAssistantEvents("t",REQUEST,e -> {},context,ignored -> {});
                    assertThat(context.budget().snapshot()).containsEntry("settled_tokens",40L).containsEntry("calls",2);
                    assertThat(((Map<?,?>)context.budget().snapshot().get("by_kind")).containsKey("generation")).isTrue();
                    assertThat(((Map<?,?>)context.budget().snapshot().get("by_kind")).containsKey("drift_check")).isTrue();
                    assertThat(count.get()).isEqualTo(2);
                }
                assertThat(events).anySatisfy(e -> { assertThat(e.event()).isEqualTo("model_call_completed"); assertThat(e.data()).containsEntry("call_kind","drift_check").containsEntry("usage_final",true); });
            });
        } finally { server.stop(0); }
    }
    @Test void aJudgeCannotSpendAgainAfterGenerationHasConsumedTheSharedCallBudget() throws Exception {
        var wire = new AtomicReference<JsonNode>(); var count = new AtomicInteger(); var server = server("DRIFT",wire,count);
        try {
            runner(server).withPropertyValues("rs.agent.reasoning.max-model-calls=1").run(ctx -> {
                var model = ctx.getBean(AgentModelStreamClient.class); var context = new AgentInterruptContext("t","s");
                try (var turn = model.reasoningPolicy().openTurn(context,REQUEST,e -> {},model)) {
                    model.streamAssistantEvents("t",REQUEST,e -> {},context,ignored -> {});
                    var decision = turn.beforeTool(AgentModelStreamEvent.toolUse("recommend_candidates",Map.of("query","帐篷")));
                    assertThat(decision.status()).isEqualTo("UNKNOWN"); assertThat(decision.blocked()).isTrue(); assertThat(count.get()).isEqualTo(1);
                    assertThat(context.budget().snapshot()).containsEntry("calls",1).containsEntry("settled_tokens",20L);
                }
            });
        } finally { server.stop(0); }
    }
    private ApplicationContextRunner runner(HttpServer server) {
        return new ApplicationContextRunner().withConfiguration(AutoConfigurations.of(OpenAiChatAutoConfiguration.class,ChatClientAutoConfiguration.class,ToolCallingAutoConfiguration.class))
                .withUserConfiguration(AgentModelProviderConfiguration.class).withPropertyValues("rs.agent.model-provider.type=spring_ai",
                        "spring.ai.openai.base-url=http://127.0.0.1:"+server.getAddress().getPort(), "spring.ai.openai.api-key=engineering-placeholder",
                        "spring.ai.openai.chat.max-retries=0", "spring.ai.openai.chat.options.model=fixture-model", "spring.ai.openai.chat.options.max-tokens=1024",
                        "spring.ai.chat.client.tool-calling.enabled=false");
    }
    private HttpServer server(String reply, AtomicReference<JsonNode> wire, AtomicInteger count) throws Exception {
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1",0),0); var json = new ObjectMapper();
        server.createContext("/", exchange -> {
            var request = json.readTree(exchange.getRequestBody()); wire.set(request); count.incrementAndGet();
            String content = "回答";
            if (request.path("tool_choice").asText().equals("none")) {
                var data = json.readTree(request.path("messages").get(1).path("content").asText());
                content = reply.equals("invalid") ? "not-json" : json.writeValueAsString(Map.of("decision",reply,"query",data.path("candidate_query").asText(),"reason",reply.equals("DRIFT") ? "unrelated_goal" : "supports_goal"));
            }
            String chunk = json.writeValueAsString(Map.of("id","fixture","object","chat.completion.chunk","model","fixture-model","choices",List.of(Map.of("index",0,"delta",Map.of("content",content)))));
            String usage = json.writeValueAsString(Map.of("id","fixture","object","chat.completion.chunk","model","fixture-model","choices",List.of(),"usage",Map.of("prompt_tokens",15,"completion_tokens",5,"total_tokens",20)));
            byte[] body = ("data: "+chunk+"\n\ndata: "+usage+"\n\ndata: [DONE]\n\n").getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type","text/event-stream"); exchange.sendResponseHeaders(200,body.length);
            exchange.getResponseBody().write(body); exchange.close();
        }); server.start(); return server;
    }
}
