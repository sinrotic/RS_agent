package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.domain.vo.AgentToolCallVO;
import com.sinrotic.rs.agent.service.impl.AgentFinishReason;
import com.sinrotic.rs.agent.service.impl.AgentLoop;
import com.sinrotic.rs.agent.service.impl.AgentLoopHookContext;
import com.sinrotic.rs.agent.service.impl.AgentLoopHookEvent;
import com.sinrotic.rs.agent.service.impl.AgentLoopHookResult;
import com.sinrotic.rs.agent.service.impl.AgentLoopResult;
import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.AgentProfile;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentInterrupter;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.RagAgentLoop;
import com.sinrotic.rs.agent.service.impl.RsAgentLoop;
import com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

class AgentLoopTest {

    @Test
    void interruptWhileWaitingForModelCapacityReleasesTurnWithoutCallingModel() throws Exception {
        var properties = new com.sinrotic.rs.agent.config.AgentExecutionProperties();
        properties.setMaxModelStreams(1);
        properties.setModelStreamAcquireTimeoutMs(5000);
        var limiter = new AgentExecutionLimiter(properties);
        var interrupter = new InMemoryAgentInterrupter();
        var occupied = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var beforeModel = new CountDownLatch(1);
        var requestId = new java.util.concurrent.atomic.AtomicReference<String>();
        var modelCalls = new AtomicInteger();
        var observations = new java.util.concurrent.CopyOnWriteArrayList<AgentStreamEventVO>();
        try (var workers = java.util.concurrent.Executors.newVirtualThreadPerTaskExecutor();
             var tools = new VirtualThreadAgentToolUseExecutor()) {
            var holder = workers.submit(() -> limiter.runWithModelStream(() -> {
                occupied.countDown();
                release.await();
            }));
            assertThat(occupied.await(2, TimeUnit.SECONDS)).isTrue();
            var loop = new RsAgentLoop(new InMemoryAgentRuntimeConfigurationService(), tools,
                    (id, request, consumer) -> {
                        modelCalls.incrementAndGet();
                        consumer.accept(AgentModelStreamEvent.token("完成"));
                        consumer.accept(AgentModelStreamEvent.done());
                    }, context -> {
                        if (AgentLoopHookEvent.BEFORE_MODEL_CALL.equals(context.eventName())) {
                            requestId.set(context.requestId());
                            beforeModel.countDown();
                        }
                        return AgentLoopHookResult.proceed();
                    }, interrupter, limiter);
            var turn = workers.submit(() -> loop.run(new AgentChatRequestDTO(
                    "queued-model-session", "profile", "推荐鼠标", 5, Map.of()), observations::add));
            try {
                assertThat(beforeModel.await(2, TimeUnit.SECONDS)).isTrue();
                assertThat(interrupter.interrupt(requestId.get(), "user_stop")).isTrue();
                assertThat(turn.get(1, TimeUnit.SECONDS).finishReason()).isEqualTo(AgentFinishReason.INTERRUPTED);
                assertThat(modelCalls).hasValue(0);
                assertThat(observations).noneMatch(event -> event.event().startsWith("model_call_"));
            } finally {
                release.countDown();
                holder.get(2, TimeUnit.SECONDS);
                turn.get(2, TimeUnit.SECONDS);
            }
            assertThat(limiter.callWithModelStream(() -> "available")).isEqualTo("available");
        }
    }

    @Test
    void repeatedDependencyFailuresForceFinalAnswerBeforeExhaustingModelLoops() {
        AtomicInteger calls = new AtomicInteger();
        AgentModelStreamClient model = (requestId, request, consumer) -> {
            calls.incrementAndGet();
            if (Boolean.TRUE.equals(request.resolvedContext().get("final_answer_only"))) {
                consumer.accept(AgentModelStreamEvent.toolUse("emit_final_answer", Map.of(
                        "blocks", List.of(Map.of("type", "text", "content", "检索暂时不可用，请稍后重试。")))));
            } else {
                consumer.accept(AgentModelStreamEvent.toolUse("rag_support", Map.of("query", "背包")));
            }
        };
        try (var executor = new VirtualThreadAgentToolUseExecutor(event -> {
            throw new IllegalStateException("dependency unavailable");
        })) {
            var loop = new RsAgentLoop(new InMemoryAgentRuntimeConfigurationService(), executor, model);
            var result = loop.run(new AgentChatRequestDTO("failure-session", "profile", "推荐背包", 1, Map.of()), event -> {});
            assertThat(calls).hasValue(3);
            assertThat(result.finishReason()).isEqualTo(AgentFinishReason.FINAL_ANSWER);
            assertThat(result.toolCalls()).filteredOn(tool -> "FAILED".equals(tool.status())).hasSize(2);
        }
    }

    @Test
    void subclassCanProvideAgentProfileAndCustomToolServices() {
        TestAgentLoop loop = new TestAgentLoop();
        List<AgentStreamEventVO> events = new ArrayList<>();

        AgentLoopResult result = loop.run(new AgentChatRequestDTO(
                "sess_custom_agent",
                "A1XYZ",
                "Run custom tool",
                1,
                Map.of("scene", "custom")
        ), events::add);

        assertThat(result.agentName()).isEqualTo("test_agent");
        assertThat(result.finishReason()).isEqualTo(AgentFinishReason.FINAL_ANSWER);
        assertThat(result.assistantMessage()).isEqualTo("custom answer");
        assertThat(result.toolCalls()).hasSize(1);
        assertThat(result.toolCalls().getFirst().toolName()).isEqualTo("custom_lookup");
        assertThat(result.toolCalls().getFirst().service()).isEqualTo("rs-service-custom");
        assertThat(events).extracting(AgentStreamEventVO::event)
                .containsSubsequence("tool_use", "tool_result", "token", "done");
    }

    @Test
    void emitFinalAnswerProducesUserVisibleAnswerBlocksAndStopsLoop() {
        AtomicBoolean internalExecutorCalled = new AtomicBoolean(false);
        AgentLoop loop = new AgentLoop(
                new AgentProfile("test_agent", "Structured answer test agent.", Map.of(
                        "emit_final_answer", "rs-service-agent"
                )),
                new InMemoryAgentRuntimeConfigurationService(),
                new VirtualThreadAgentToolUseExecutor(event -> {
                    internalExecutorCalled.set(true);
                    return Map.of("status", "SHOULD_NOT_RUN");
                }),
                (requestId, request, consumer) -> consumer.accept(AgentModelStreamEvent.toolUse(
                        "emit_final_answer",
                        Map.of("blocks", List.of(
                                finalAnswerBlock("text", "我建议先看这两款。", null, null, null),
                                finalAnswerBlock("product_cards", null, "cards_001", null, "grid"),
                                finalAnswerBlock("text", "第一款更适合通勤，第二款更适合防水。", null, null, null)
                        ))
                ))
        ) {
        };
        List<AgentStreamEventVO> events = new ArrayList<>();

        AgentLoopResult result = loop.run(new AgentChatRequestDTO(
                "sess_blocks",
                "A1XYZ",
                "推荐通勤包",
                2,
                Map.of()
        ), events::add);

        assertThat(internalExecutorCalled).isFalse();
        assertThat(result.finishReason()).isEqualTo(AgentFinishReason.FINAL_ANSWER);
        assertThat(result.assistantMessage()).isEqualTo("我建议先看这两款。\n第一款更适合通勤，第二款更适合防水。");
        assertThat(result.toolCalls()).isEmpty();
        events.removeIf(event -> event.event().startsWith("model_call_"));
        assertThat(events).extracting(AgentStreamEventVO::event)
                .containsExactly("answer_block", "answer_block", "answer_block", "done");
        assertThat(events.getLast().data()).containsEntry("finish_reason", "FINAL_ANSWER");
        assertThat(events.get(0).data())
                .containsEntry("type", "text")
                .containsEntry("content", "我建议先看这两款。");
        assertThat(events.get(1).data())
                .containsEntry("type", "product_cards")
                .containsEntry("card_set_id", "cards_001");
    }

    @Test
    void rsAgentLoopMapsSpecificRecommendToolsToRecommendService() {
        AgentLoop loop = new RsAgentLoop(
                new InMemoryAgentRuntimeConfigurationService(),
                new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                new SingleToolThenDoneModelStreamClient("recommend_semantic_recall")
        );
        List<AgentStreamEventVO> events = new ArrayList<>();

        AgentLoopResult result = loop.run(new AgentChatRequestDTO(
                "sess_recommend_tool",
                "A1XYZ",
                "recommend portable staplers",
                1,
                Map.of()
        ), events::add);

        assertThat(result.toolCalls()).hasSize(1);
        assertThat(result.toolCalls().getFirst().toolName()).isEqualTo("recommend_semantic_recall");
        assertThat(result.toolCalls().getFirst().service()).isEqualTo("rs-service-recommend");
    }

    @Test
    void rsAgentLoopRoutesRagSupportToRecommendService() {
        AgentLoop loop = new RsAgentLoop(
                new InMemoryAgentRuntimeConfigurationService(),
                new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                new SingleToolThenDoneModelStreamClient("rag_support")
        );
        List<AgentStreamEventVO> events = new ArrayList<>();

        AgentLoopResult result = loop.run(new AgentChatRequestDTO(
                "sess_rag_route",
                "A1XYZ",
                "recommend bluetooth earbuds",
                1,
                Map.of()
        ), events::add);

        assertThat(result.toolCalls()).hasSize(1);
        assertThat(result.toolCalls().getFirst().toolName()).isEqualTo("rag_support");
        assertThat(result.toolCalls().getFirst().service()).isEqualTo("rs-service-recommend");
    }

    @Test
    void ragAgentLoopUsesRecommendEvidenceSearchTool() {
        AgentLoop loop = new RagAgentLoop(
                new InMemoryAgentRuntimeConfigurationService(),
                new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                new SingleToolThenDoneModelStreamClient("rag_evidence_search")
        );
        List<AgentStreamEventVO> events = new ArrayList<>();

        AgentLoopResult result = loop.run(new AgentChatRequestDTO(
                "sess_rag_agent",
                "A1XYZ",
                "compress candidate evidence",
                1,
                Map.of()
        ), events::add);

        assertThat(result.agentName()).isEqualTo("rag_agent");
        assertThat(result.toolCalls()).hasSize(1);
        assertThat(result.toolCalls().getFirst().toolName()).isEqualTo("rag_evidence_search");
        assertThat(result.toolCalls().getFirst().service()).isEqualTo("rs-service-recommend");
    }

    @Test
    void preToolUseCanRewriteArgumentsBeforeExecutionAndPostToolUseSeesResult() {
        List<String> hookEvents = new ArrayList<>();
        AtomicBoolean executorSawUpdatedQuery = new AtomicBoolean(false);
        AgentLoop loop = new AgentLoop(
                new AgentProfile("test_agent", "Hook test agent.", Map.of("custom_lookup", "rs-service-custom")),
                new InMemoryAgentRuntimeConfigurationService(),
                new VirtualThreadAgentToolUseExecutor(event -> {
                    executorSawUpdatedQuery.set("rewritten query".equals(event.arguments().get("query")));
                    return Map.of("status", "SUCCESS", "query", event.arguments().get("query"));
                }),
                new SingleToolThenDoneModelStreamClient("custom_lookup"),
                context -> {
                    hookEvents.add(context.eventName());
                    if (AgentLoopHookEvent.PRE_TOOL_USE.equals(context.eventName())) {
                        return AgentLoopHookResult.proceed()
                                .withUpdatedToolArguments(Map.of("query", "rewritten query"));
                    }
                    return AgentLoopHookResult.proceed();
                }
        ) {
        };

        AgentLoopResult result = loop.run(new AgentChatRequestDTO(
                "sess_hooks",
                "A1XYZ",
                "run hook tool",
                1,
                Map.of()
        ), ignored -> {
        });

        assertThat(executorSawUpdatedQuery).isTrue();
        assertThat(result.toolCalls()).hasSize(1);
        assertThat(result.toolCalls().getFirst().metadata()).containsEntry("query", "rewritten query");
        assertThat(hookEvents).contains(
                AgentLoopHookEvent.SESSION_START,
                AgentLoopHookEvent.USER_PROMPT_SUBMIT,
                AgentLoopHookEvent.BEFORE_MODEL_CALL,
                AgentLoopHookEvent.PRE_TOOL_USE,
                AgentLoopHookEvent.POST_TOOL_USE
        );
    }

    @Test
    void sameModelTurnConcurrentSafeToolsAreDispatchedWithoutStoppingTheStream() {
        AtomicInteger modelCalls = new AtomicInteger();
        AtomicInteger runningTools = new AtomicInteger();
        AtomicInteger maxRunningTools = new AtomicInteger();
        AgentLoop loop = new AgentLoop(
                new AgentProfile("test_agent", "Concurrent tool test agent.", Map.of(
                        "load_skill", "rs-service-agent",
                        "rag_support", "rs-service-recommend"
                )),
                new InMemoryAgentRuntimeConfigurationService(),
                new VirtualThreadAgentToolUseExecutor(event -> {
                    int running = runningTools.incrementAndGet();
                    maxRunningTools.accumulateAndGet(running, Math::max);
                    try {
                        Thread.sleep(150);
                    } catch (InterruptedException error) {
                        Thread.currentThread().interrupt();
                        throw new IllegalStateException(error);
                    } finally {
                        runningTools.decrementAndGet();
                    }
                    return Map.of("status", "SUCCESS", "tool_name", event.toolName());
                }),
                (requestId, request, consumer) -> {
                    if (modelCalls.incrementAndGet() == 1) {
                        consumer.accept(AgentModelStreamEvent.toolUse(
                                "toolu_skill",
                                "load_skill",
                                Map.of("skill_name", "explicit-need-recommendation")
                        ));
                        consumer.accept(AgentModelStreamEvent.toolUse(
                                "toolu_rag",
                                "rag_support",
                                Map.of("query", "bluetooth earbuds")
                        ));
                        consumer.accept(AgentModelStreamEvent.done());
                        return;
                    }
                    consumer.accept(AgentModelStreamEvent.token("done"));
                    consumer.accept(AgentModelStreamEvent.done());
                }
        ) {
        };
        List<AgentStreamEventVO> events = new ArrayList<>();

        AgentLoopResult result = loop.run(new AgentChatRequestDTO(
                "sess_concurrent_tools",
                "A1XYZ",
                "recommend earbuds",
                1,
                Map.of()
        ), events::add);

        assertThat(maxRunningTools.get()).isGreaterThanOrEqualTo(2);
        assertThat(result.toolCalls()).extracting(AgentToolCallVO::toolCallId)
                .containsExactly("toolu_skill", "toolu_rag");
        assertThat(events).extracting(AgentStreamEventVO::event)
                .containsSubsequence("tool_use", "tool_use", "tool_result", "tool_result", "token", "done");
    }

    @Test
    void postModelHookReceivesTokenUsageFromModelStream() {
        List<Map<String, Object>> postModelMetadata = new ArrayList<>();
        AgentLoop loop = new AgentLoop(
                new AgentProfile("test_agent", "Usage hook test agent.", Map.of()),
                new InMemoryAgentRuntimeConfigurationService(),
                new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                (requestId, request, consumer) -> {
                    consumer.accept(AgentModelStreamEvent.token("answer"));
                    consumer.accept(AgentModelStreamEvent.usage(Map.of(
                            "prompt_tokens", 100,
                            "completion_tokens", 25,
                            "total_tokens", 125
                    )));
                    consumer.accept(AgentModelStreamEvent.done());
                },
                context -> {
                    if (AgentLoopHookEvent.POST_MODEL_STREAM.equals(context.eventName())) {
                        postModelMetadata.add(context.metadata());
                    }
                    return AgentLoopHookResult.proceed();
                }
        ) {
        };
        List<AgentStreamEventVO> events = new ArrayList<>();

        loop.run(new AgentChatRequestDTO(
                "sess_usage",
                "A1XYZ",
                "count tokens",
                1,
                Map.of()
        ), events::add);

        assertThat(events).extracting(AgentStreamEventVO::event)
                .contains("token", "model_usage", "done");
        assertThat(postModelMetadata).hasSize(1);
        assertThat(postModelMetadata.getFirst())
                .containsEntry("prompt_tokens", 100)
                .containsEntry("completion_tokens", 25)
                .containsEntry("total_tokens", 125);
    }

    @Test
    void stopHookCanBlockFinalizationAndForceAnotherLoop() {
        AtomicInteger stopCount = new AtomicInteger();
        StopThenFinalModelStreamClient model = new StopThenFinalModelStreamClient();
        AgentLoop loop = new AgentLoop(
                new AgentProfile("test_agent", "Stop hook test agent.", Map.of()),
                new InMemoryAgentRuntimeConfigurationService(),
                new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                model,
                context -> {
                    if (AgentLoopHookEvent.STOP.equals(context.eventName()) && stopCount.getAndIncrement() == 0) {
                        return AgentLoopHookResult.block("Need one more pass before final answer.");
                    }
                    return AgentLoopHookResult.proceed();
                }
        ) {
        };

        AgentLoopResult result = loop.run(new AgentChatRequestDTO(
                "sess_stop_hook",
                "A1XYZ",
                "answer after stop hook",
                1,
                Map.of()
        ), ignored -> {
        });

        assertThat(model.calls).isEqualTo(2);
        assertThat(stopCount.get()).isEqualTo(2);
        assertThat(result.finishReason()).isEqualTo(AgentFinishReason.FINAL_ANSWER);
        assertThat(result.assistantMessage()).isEqualTo("draft final");
    }

    @Test
    void interruptDuringModelStreamStopsLoopAndEmitsInterruptedEvent() {
        InMemoryAgentInterrupter interrupter = new InMemoryAgentInterrupter();
        List<String> hookEvents = new ArrayList<>();
        AgentLoop loop = new AgentLoop(
                new AgentProfile("test_agent", "Interrupt model stream agent.", Map.of()),
                new InMemoryAgentRuntimeConfigurationService(),
                new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SHOULD_NOT_RUN")),
                (requestId, request, consumer) -> {
                    consumer.accept(AgentModelStreamEvent.token("partial "));
                    interrupter.interrupt(requestId, "user_stop");
                    consumer.accept(AgentModelStreamEvent.token("ignored"));
                },
                context -> {
                    hookEvents.add(context.eventName());
                    return AgentLoopHookResult.proceed();
                },
                interrupter
        ) {
        };
        List<AgentStreamEventVO> events = new ArrayList<>();

        AgentLoopResult result = loop.run(new AgentChatRequestDTO(
                "sess_interrupt_model",
                "A1XYZ",
                "stop model stream",
                1,
                Map.of()
        ), events::add);

        assertThat(result.assistantMessage()).isEqualTo("partial ");
        assertThat(result.finishReason()).isEqualTo(AgentFinishReason.INTERRUPTED);
        assertThat(events.stream().filter(event -> event.event().equals("model_call_completed")).findFirst().orElseThrow().data())
                .containsEntry("status", "interrupted").containsEntry("usage_final", false);
        events.removeIf(event -> event.event().startsWith("model_call_"));
        assertThat(events).extracting(AgentStreamEventVO::event)
                .containsExactly("token", "interrupted", "done");
        assertThat(events.get(1).data())
                .containsEntry("reason", "user_stop");
        assertThat(events.get(2).data()).containsEntry("finish_reason", "INTERRUPTED");
        assertThat(hookEvents).contains(AgentLoopHookEvent.INTERRUPT);
    }

    @Test
    void interruptDuringToolUseCancelsFutureAndReturnsInterruptedToolResult() throws Exception {
        InMemoryAgentInterrupter interrupter = new InMemoryAgentInterrupter();
        CountDownLatch toolStarted = new CountDownLatch(1);
        AtomicBoolean toolThreadInterrupted = new AtomicBoolean(false);
        AgentLoop loop = new AgentLoop(
                new AgentProfile("test_agent", "Interrupt tool agent.", Map.of("custom_lookup", "rs-service-custom")),
                new InMemoryAgentRuntimeConfigurationService(),
                new VirtualThreadAgentToolUseExecutor(event -> {
                    toolStarted.countDown();
                    try {
                        Thread.sleep(10_000);
                    } catch (InterruptedException ex) {
                        toolThreadInterrupted.set(true);
                        Thread.currentThread().interrupt();
                        throw new IllegalStateException("tool interrupted", ex);
                    }
                    return Map.of("status", "SHOULD_NOT_FINISH");
                }),
                (requestId, request, consumer) -> consumer.accept(AgentModelStreamEvent.toolUse(
                        "toolu_interrupt",
                        "custom_lookup",
                        Map.of("query", "slow")
                )),
                context -> AgentLoopHookResult.proceed(),
                interrupter
        ) {
        };
        List<AgentStreamEventVO> events = new ArrayList<>();

        Thread runner = Thread.ofVirtual().start(() -> loop.run(new AgentChatRequestDTO(
                "sess_interrupt_tool",
                "A1XYZ",
                "stop slow tool",
                1,
                Map.of()
        ), events::add));
        assertThat(toolStarted.await(2, TimeUnit.SECONDS)).isTrue();
        String requestId = events.stream()
                .filter(event -> "tool_use".equals(event.event()))
                .findFirst()
                .orElseThrow()
                .requestId();

        interrupter.interrupt(requestId, "user_stop");
        runner.join(2_000);

        assertThat(runner.isAlive()).isFalse();
        assertThat(toolThreadInterrupted).isTrue();
        assertThat(events).extracting(AgentStreamEventVO::event)
                .contains("tool_use", "tool_result", "interrupted", "done");
        AgentStreamEventVO toolResult = events.stream()
                .filter(event -> "tool_result".equals(event.event()))
                .findFirst()
                .orElseThrow();
        assertThat(toolResult.data()).containsEntry("status", "INTERRUPTED");
    }

    private static Map<String, Object> finalAnswerBlock(
            String type,
            String content,
            String cardSetId,
            List<String> itemIds,
            String layout
    ) {
        Map<String, Object> block = new LinkedHashMap<>();
        block.put("type", type);
        block.put("content", content);
        block.put("card_set_id", cardSetId);
        block.put("item_ids", itemIds);
        block.put("layout", layout);
        return block;
    }

    private static class TestAgentLoop extends AgentLoop {

        TestAgentLoop() {
            super(
                    new AgentProfile(
                            "test_agent",
                            "Agent used to prove subclass-specific tool registration.",
                            Map.of("custom_lookup", "rs-service-custom")
                    ),
                    new InMemoryAgentRuntimeConfigurationService(),
                    new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                    new TestModelStreamClient()
            );
        }
    }

    private static class TestModelStreamClient implements AgentModelStreamClient {

        private int calls;

        @Override
        public void streamAssistantEvents(
                String requestId,
                AgentChatRequestDTO request,
                java.util.function.Consumer<AgentModelStreamEvent> consumer
        ) {
            if (++calls == 1) {
                consumer.accept(AgentModelStreamEvent.toolUse("custom_lookup", Map.of("key", "value")));
                return;
            }
            consumer.accept(AgentModelStreamEvent.token("custom answer"));
            consumer.accept(AgentModelStreamEvent.done());
        }
    }

    private static class SingleToolThenDoneModelStreamClient implements AgentModelStreamClient {

        private final String toolName;

        private int calls;

        SingleToolThenDoneModelStreamClient(String toolName) {
            this.toolName = toolName;
        }

        @Override
        public void streamAssistantEvents(
                String requestId,
                AgentChatRequestDTO request,
                java.util.function.Consumer<AgentModelStreamEvent> consumer
        ) {
            if (++calls == 1) {
                consumer.accept(AgentModelStreamEvent.toolUse(toolName, Map.of("query", "portable staplers")));
                return;
            }
            consumer.accept(AgentModelStreamEvent.token("done"));
            consumer.accept(AgentModelStreamEvent.done());
        }
    }

    private static class StopThenFinalModelStreamClient implements AgentModelStreamClient {

        private int calls;

        @Override
        public void streamAssistantEvents(
                String requestId,
                AgentChatRequestDTO request,
                java.util.function.Consumer<AgentModelStreamEvent> consumer
        ) {
            if (++calls == 1) {
                consumer.accept(AgentModelStreamEvent.token("draft "));
                consumer.accept(AgentModelStreamEvent.done());
                return;
            }
            consumer.accept(AgentModelStreamEvent.token("final"));
            consumer.accept(AgentModelStreamEvent.done());
        }
    }
}
