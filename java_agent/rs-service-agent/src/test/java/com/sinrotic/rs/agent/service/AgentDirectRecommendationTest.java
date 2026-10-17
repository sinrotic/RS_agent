package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentDirectRecommendationProperties;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSystemPromptUpdateDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.service.impl.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import static org.assertj.core.api.Assertions.*;

class AgentDirectRecommendationTest {
    @ParameterizedTest @ValueSource(booleans = {false, true})
    void guardedSynthesisStillUsesModelAndRetainsDeliveryHistoryAndReplay(boolean directEnabled) {
        var properties = properties(directEnabled); properties.setLlmSynthesisEnabled(true);
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        var calls = new AtomicInteger(); var observed = new AtomicReference<AgentChatRequestDTO>();
        var service = new InMemoryAgentOrchestrationService((id, request, consumer) -> {
            calls.incrementAndGet(); observed.set(request);
            consumer.accept(AgentModelStreamEvent.toolUse("emit_final_answer", Map.of("blocks",
                    List.of(Map.of("type", "text", "content", "这是模型基于商品证据生成的推荐。")))));
        }, new VirtualThreadAgentToolUseExecutor(), runtime);
        service.setDirectRecommendation(new AgentDirectRecommendation(properties, runtime));
        var delivery = delivery("Headphones", new BigDecimal("89.5"), List.of());
        service.setRecommendationService(new AgentRecommendationService() {
            public List<AgentRecommendedItemVO> recommend(AgentChatRequestDTO request) { return delivery.items(); }
            public AgentRecommendationDelivery recommendDelivery(AgentChatRequestDTO request) { return delivery; }
        });
        var request = request("llm-synthesis", "推荐100美元以内的耳机");
        var response = service.chat(request);
        assertThat(calls).hasValue(1);
        assertThat(response.assistantMessage()).isEqualTo("这是模型基于商品证据生成的推荐。");
        assertThat(observed.get().resolvedContext()).containsEntry("final_answer_only", true)
                .containsEntry("recommendation_synthesis_only", true);
        assertThat(observed.get().resolvedContext().get("constraints")).isEqualTo(Map.of("price_max", new BigDecimal("100")));
        assertThat(response.cardSetId()).isEqualTo("delivery");
        assertThat(service.chat(request)).usingRecursiveComparison().ignoringFields("toolCalls").isEqualTo(response);
        assertThat(calls).hasValue(1);
        assertThat(service.sessionTurns("llm-synthesis", "profile").turns()).hasSize(1);
        service.chat(new AgentChatRequestDTO("llm-synthesis", "profile", "推荐耳机", 5, Map.of()));
        assertThat(observed.get().resolvedContext()).doesNotContainKeys("recommendation_synthesis_only");
        assertThat(calls).hasValue(2);
    }

    @Test void realCatalogTitlesRemainCompleteAndOversizedTitlesStillFallBack() {
        var direct = new AgentDirectRecommendation(properties(true), new InMemoryAgentRuntimeConfigurationService());
        var plan = direct.prepare(request("catalog-title", "推荐鼠标"), true, true).orElseThrow();
        String title = "Ergonomic Wireless Mouse ".repeat(8);
        var response = new AgentRecommendationDelivery(List.of(new AgentRecommendedItemVO(
                "mouse", title, "Electronics > Keyboards, Mice & Accessories > Mice", .8, "", "delivery")), List.of());
        assertThat(direct.answer(plan, response).orElseThrow().toString()).contains(title);
        var oversized = new AgentRecommendationDelivery(List.of(new AgentRecommendedItemVO(
                "mouse", "x".repeat(513), "Mice", .8, "", "delivery")), List.of());
        assertThat(direct.answer(plan, oversized)).isEmpty();
    }
    private AgentDirectRecommendationProperties properties(boolean enabled) {
        var properties = new AgentDirectRecommendationProperties();
        properties.setEnabled(enabled); properties.setCatalogCurrency("USD"); return properties;
    }
    private AgentRecommendationDelivery delivery(String category, BigDecimal price, List<String> degraded) {
        return new AgentRecommendationDelivery(List.of(new AgentRecommendedItemVO("item", "Actual Headphones",
                category, .8, "generic", "delivery")), degraded, Map.of("item", new AgentRecommendationFact(price)));
    }
    private InMemoryAgentOrchestrationService service(AgentDirectRecommendationProperties properties,
            InMemoryAgentRuntimeConfigurationService runtime, AtomicInteger modelCalls, AgentRecommendationDelivery delivery) {
        var service = new InMemoryAgentOrchestrationService((id, request, consumer) -> {
            modelCalls.incrementAndGet();
            consumer.accept(AgentModelStreamEvent.toolUse("emit_final_answer", Map.of("blocks",
                    List.of(Map.of("type", "text", "content", "原 Agent 回答")))));
        }, new VirtualThreadAgentToolUseExecutor(), runtime);
        service.setDirectRecommendation(new AgentDirectRecommendation(properties, runtime));
        service.setRecommendationService(new AgentRecommendationService() {
            public List<AgentRecommendedItemVO> recommend(AgentChatRequestDTO request) { return delivery.items(); }
            public AgentRecommendationDelivery recommendDelivery(AgentChatRequestDTO request) { return delivery; }
        });
        return service;
    }
    private AgentChatRequestDTO request(String id, String message) {
        return new AgentChatRequestDTO(id, "profile", message, 5, Map.of("client_turn_id", "turn", "a2ui_state", List.of()));
    }

    @Test void directAnswerUsesNormalProjectionHistoryAndRetryWithoutModelOrNewDelivery() {
        var calls = new AtomicInteger(); var runtime = new InMemoryAgentRuntimeConfigurationService();
        var service = service(properties(true), runtime, calls, delivery("Electronics > Headphones", new BigDecimal("89.5"), List.of()));
        var recommended = new AtomicInteger(); var captured = new AtomicReference<AgentChatRequestDTO>();
        var response = delivery("Electronics > Headphones", new BigDecimal("89.5"), List.of());
        service.setRecommendationService(new AgentRecommendationService() {
            public List<AgentRecommendedItemVO> recommend(AgentChatRequestDTO request) { return response.items(); }
            public AgentRecommendationDelivery recommendDelivery(AgentChatRequestDTO request) {
                captured.set(request); recommended.incrementAndGet(); return response;
            }
        });
        var events = new ArrayList<AgentStreamEventVO>();
        var request = request("first", "请推荐100美元以内的耳机");
        service.streamChat(request, events::add);
        assertThat(calls).hasValue(0);
        assertThat(captured.get().resolvedContext().get("constraints")).isEqualTo(Map.of("price_max", new BigDecimal("100")));
        var history = service.sessionTurns("first", "profile").turns().getFirst();
        assertThat(history.assistantMessage()).contains("89.5 USD", "预算内", "耳机类目");
        assertThat(history.answerBlocks()).hasSize(2);
        assertThat(history.finishReason()).isEqualTo("FINAL_ANSWER");
        assertThat(events.stream().filter(event -> event.event().equals("answer_block")).count()).isEqualTo(2);
        assertThat(events.getLast().event()).isEqualTo("done");
        assertThat(service.chat(request).cardSetId()).isEqualTo("delivery");
        assertThat(recommended).hasValue(1);
        assertThat(service.sessionTurns("first").turns()).hasSize(1);
        // Later Turns cannot silently ignore the earlier budget.
        service.chat(new AgentChatRequestDTO("first", "profile", "推荐耳机", 5, Map.of()));
        assertThat(calls).hasValue(1);
    }

    @ParameterizedTest @ValueSource(booleans = {false, true})
    void disabledUnknownCurrencyAndUnsupportedLanguageKeepOriginalModelPath(boolean synthesis) {
        for (String message : List.of("推荐300元以内的耳机", "推荐耳机，不要某品牌", "比较耳机", "推荐100美元左右的耳机",
                "推荐防水耳机", "不推荐耳机，只说建议", "推荐耳机并解释详细原因", "推荐100美元以内200元以下的耳机")) {
            var calls = new AtomicInteger();
            var options = properties(true); options.setLlmSynthesisEnabled(synthesis);
            var service = service(options, new InMemoryAgentRuntimeConfigurationService(), calls,
                    delivery("Headphones", BigDecimal.ONE, List.of()));
            assertThat(service.chat(request("unsupported", message)).assistantMessage()).isEqualTo("原 Agent 回答");
            assertThat(calls).hasValue(1);
        }
        var calls = new AtomicInteger();
        service(properties(false), new InMemoryAgentRuntimeConfigurationService(), calls,
                delivery("Headphones", BigDecimal.ONE, List.of())).chat(request("disabled", "推荐耳机"));
        assertThat(calls).hasValue(1);
    }

    @ParameterizedTest @ValueSource(booleans = {false, true})
    void missingPriceOverBudgetForeignCategoryAndDegradationUseSameDeliveryWithAgent(boolean synthesis) {
        for (var response : List.of(delivery("Headphones", null, List.of()), delivery("Headphones", new BigDecimal("101"), List.of()),
                delivery("Headphone Accessories", BigDecimal.ONE, List.of()),
                delivery(">>>", BigDecimal.ONE, List.of()),
                delivery("Keyboards", BigDecimal.ONE, List.of()), delivery("Headphones", BigDecimal.ONE, List.of("model_rank_unavailable")),
                delivery("Headphones", BigDecimal.ONE, List.of("unknown_private_degradation")))) {
            var calls = new AtomicInteger(); var count = new AtomicInteger();
            var runtime = new InMemoryAgentRuntimeConfigurationService();
            var options = properties(true); options.setLlmSynthesisEnabled(synthesis);
            var service = service(options, runtime, calls, response);
            service.setRecommendationService(new AgentRecommendationService() {
                public List<AgentRecommendedItemVO> recommend(AgentChatRequestDTO request) { return response.items(); }
                public AgentRecommendationDelivery recommendDelivery(AgentChatRequestDTO request) { count.incrementAndGet(); return response; }
            });
            assertThat(service.chat(request("facts", "推荐100美元以内的耳机")).assistantMessage()).isEqualTo("原 Agent 回答");
            assertThat(calls).hasValue(1); assertThat(count).hasValue(1);
        }
    }

    @ParameterizedTest @ValueSource(booleans = {false, true})
    void runtimeEditsAndNonemptyUiCannotBypassAgent(boolean synthesis) {
        var runtime = new InMemoryAgentRuntimeConfigurationService(); var calls = new AtomicInteger();
        var options = properties(true); options.setLlmSynthesisEnabled(synthesis);
        var service = service(options, runtime, calls, delivery("Headphones", BigDecimal.ONE, List.of()));
        runtime.updateSystemPrompt(new AgentRuntimeSystemPromptUpdateDTO("custom", "需要先确认问题"));
        service.chat(request("prompt", "推荐耳机")); assertThat(calls).hasValue(1);
        var direct = new AgentDirectRecommendation(options, new InMemoryAgentRuntimeConfigurationService());
        assertThat(direct.prepare(new AgentChatRequestDTO("ui", "profile", "推荐耳机", 5,
                Map.of("a2ui_state", List.of(Map.of("surfaceId", "existing")))), true, true)).isEmpty();
        assertThat(direct.prepare(request("hook", "推荐耳机"), true, false)).isEmpty();
    }

    @Test void stoppingAtFirstEventStopsDirectAnswerAndDoesNotInvokeModel() {
        var runtime = new InMemoryAgentRuntimeConfigurationService(); var interrupter = new InMemoryAgentInterrupter();
        var model = new AtomicInteger();
        var loop = new RsAgentLoop(runtime, new VirtualThreadAgentToolUseExecutor(),
                (id, request, consumer) -> model.incrementAndGet(), new NoopAgentLoopHookDispatcher(), interrupter);
        var service = new InMemoryAgentOrchestrationService(loop);
        service.setDirectRecommendation(new AgentDirectRecommendation(properties(true), runtime));
        service.setRecommendationService(request -> delivery("Headphones", BigDecimal.ONE, List.of()).items());
        var events = new ArrayList<AgentStreamEventVO>();
        service.streamChat(request("stop", "推荐耳机"), event -> {
            events.add(event);
            if (event.event().equals("trace")) assertThat(interrupter.interruptOwned(event.requestId(), "profile", "stop")).isTrue();
        });
        assertThat(model).hasValue(0);
        assertThat(events).noneMatch(event -> event.event().equals("answer_block"));
        assertThat(service.sessionTurns("stop").turns().getFirst().finishReason()).isEqualTo("INTERRUPTED");
    }

    @Test void checkpointOnlyContextCannotBeMisclassifiedAsAnIndependentFirstTurn() {
        var runtime = new InMemoryAgentRuntimeConfigurationService(); var calls = new AtomicInteger();
        var service = service(properties(true), runtime, calls, delivery("Headphones", BigDecimal.ONE, List.of()));
        service.setTranscriptRecoveryService(id -> new com.sinrotic.rs.agent.domain.session.AgentRecoveredTranscript(
                id, "checkpoint", 3, List.of(Map.of("role", "user", "content", "预算100美元，要防水")), List.of(), List.of()));
        service.chat(request("checkpoint", "推荐耳机"));
        assertThat(calls).hasValue(1);
    }

    @Test void customLoopSubclassRetainsItsOriginalExecutionPath() {
        var runtime = new InMemoryAgentRuntimeConfigurationService(); var model = new AtomicInteger();
        var custom = new RsAgentLoop(runtime, new VirtualThreadAgentToolUseExecutor(),
                (id, request, consumer) -> {
                    model.incrementAndGet();
                    consumer.accept(AgentModelStreamEvent.toolUse("emit_final_answer", Map.of("blocks",
                            List.of(Map.of("type", "text", "content", "custom loop")))));
                }, new NoopAgentLoopHookDispatcher(), new InMemoryAgentInterrupter()) { };
        var service = new InMemoryAgentOrchestrationService(custom);
        service.setDirectRecommendation(new AgentDirectRecommendation(properties(true), runtime));
        service.setRecommendationService(request -> delivery("Headphones", BigDecimal.ONE, List.of()).items());
        assertThat(service.chat(request("custom-loop", "推荐耳机")).assistantMessage()).isEqualTo("custom loop");
        assertThat(model).hasValue(1);
    }

    @Test void eightUsersKeepSeparateDeliveriesHistoriesAndFeedbackIdentifiers() throws Exception {
        var runtime = new InMemoryAgentRuntimeConfigurationService(); var calls = new AtomicInteger();
        var service = service(properties(true), runtime, calls, delivery("Headphones", BigDecimal.ONE, List.of()));
        service.setRecommendationService(request -> List.of(new AgentRecommendedItemVO(
                "item-" + request.profileUserId(), "Headphones " + request.profileUserId(), "Headphones", .8, "", "delivery-" + request.sessionId())));
        try (var workers = java.util.concurrent.Executors.newVirtualThreadPerTaskExecutor()) {
            var futures = new ArrayList<java.util.concurrent.Future<?>>();
            for (int index = 0; index < 8; index++) {
                String id = "user-" + index;
                futures.add(workers.submit(() -> {
                    var response = service.chat(new AgentChatRequestDTO(id, id, "推荐耳机", 5, Map.of()));
                    assertThat(response.cardSetId()).isEqualTo("delivery-" + id);
                    assertThat(response.recommendedItems()).singleElement().satisfies(item ->
                            assertThat(item.itemId()).isEqualTo("item-" + id));
                    assertThat(service.sessionTurns(id, id).turns()).singleElement().satisfies(turn ->
                            assertThat(turn.recommendedItemIds()).containsExactly("item-" + id));
                    assertThatThrownBy(() -> service.sessionTurns(id, "different-owner"))
                            .isInstanceOf(AgentSessionNotFoundException.class);
                }));
            }
            for (var future : futures) future.get(5, java.util.concurrent.TimeUnit.SECONDS);
        }
        assertThat(calls).hasValue(0);
    }
}
