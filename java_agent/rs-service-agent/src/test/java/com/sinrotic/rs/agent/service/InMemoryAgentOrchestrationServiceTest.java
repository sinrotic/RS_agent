package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSystemPromptUpdateDTO;
import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.domain.vo.AgentChatVO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.agent.service.impl.AgentLoopResult;
import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentHotSessionStore;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentOrchestrationService;
import com.sinrotic.rs.agent.service.impl.RsAgentLoop;
import com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

class InMemoryAgentOrchestrationServiceTest {

    @Test
    void repeatedToolRequestsReachABoundedFinalAnswerInsteadOfFailingTheTurn() {
        var service = new InMemoryAgentOrchestrationService((requestId, request, consumer) -> {
            if (Boolean.TRUE.equals(request.resolvedContext().get("final_answer_only"))) {
                consumer.accept(AgentModelStreamEvent.toolUse("emit_final_answer", Map.of("blocks",
                        List.of(Map.of("type", "text", "content", "根据现有商品证据，这些候选尚不能确认满足全部要求。")))));
            } else {
                consumer.accept(AgentModelStreamEvent.toolUse("load_skill", Map.of("skill_name", "explicit-need-recommendation")));
                consumer.accept(AgentModelStreamEvent.done());
            }
        }, new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS", "loaded", true)));
        assertThat(service.chat(new AgentChatRequestDTO("bounded-loop", "profile", "耳机", 3, Map.of())).assistantMessage())
                .contains("根据现有商品证据");
    }

    @Test
    void ordinaryChatUsesTheSameModelLoopAndPersistsItsAnswer() {
        AtomicInteger calls = new AtomicInteger();
        var service = new InMemoryAgentOrchestrationService((requestId, request, consumer) -> {
            calls.incrementAndGet();
            consumer.accept(AgentModelStreamEvent.token("这是一段模型回答"));
            consumer.accept(AgentModelStreamEvent.done());
        }, new VirtualThreadAgentToolUseExecutor());
        var response = service.chat(new AgentChatRequestDTO("sync-loop", "profile", "帮我选商品", 6, Map.of()));
        assertThat(calls.get()).isEqualTo(1);
        assertThat(response.assistantMessage()).isEqualTo("这是一段模型回答");
        assertThat(service.sessionTurns("sync-loop").turns().getFirst().assistantMessage()).isEqualTo(response.assistantMessage());
    }

    @Test
    void chatUsesConfiguredRecommendationService() {
        InMemoryAgentOrchestrationService service = new InMemoryAgentOrchestrationService();
        AgentRecommendationService configuredService = request -> List.of(
                new AgentRecommendedItemVO("REAL-HTTP-001", "Noise Cancelling Headphones", "Audio", 0.95, "Matches commute")
        );
        service.setRecommendationService(configuredService);

        AgentChatVO chat = service.chat(new AgentChatRequestDTO(
                "sess_configured_recommendation",
                "A1XYZ",
                "Find commute headphones",
                6,
                Map.of("scene", "agent_chat")
        ));

        assertThat(chat.recommendedItems()).extracting(AgentRecommendedItemVO::itemId)
                .containsExactly("REAL-HTTP-001");
    }

    @Test
    void chatStoresTurnForSessionTrace() {
        InMemoryAgentOrchestrationService service = new InMemoryAgentOrchestrationService();
        service.setRecommendationService(request -> List.of(
                new AgentRecommendedItemVO("REAL-001", "Backpack", "Bags", 0.9, "Matched request"),
                new AgentRecommendedItemVO("REAL-002", "Organizer", "Storage", 0.8, "Matched request")
        ));

        AgentChatVO chat = service.chat(new AgentChatRequestDTO(
                "sess_001",
                "A1XYZ",
                "Find a commuter backpack",
                2,
                Map.of("scene", "chat")
        ));
        AgentSessionTraceVO trace = service.sessionTurns("sess_001");

        assertThat(chat.requestId()).startsWith("agent_req_");
        assertThat(chat.sessionId()).isEqualTo("sess_001");
        assertThat(chat.recommendedItems()).hasSize(2);
        assertThat(chat.toolCalls()).extracting("toolName")
                .containsExactly("recommend_candidates");
        assertThat(trace.turns()).hasSize(1);
        assertThat(trace.turns().getFirst().requestId()).isEqualTo(chat.requestId());
        assertThat(trace.turns().getFirst().recommendedItemIds()).containsExactly("REAL-001", "REAL-002");
    }

    @Test
    void platformTraceReturnsEmptySessionWhenNoTurnsExist() {
        InMemoryAgentOrchestrationService service = new InMemoryAgentOrchestrationService();

        AgentSessionTraceVO trace = service.platformSessionTrace("missing_session");

        assertThat(trace.sessionId()).isEqualTo("missing_session");
        assertThat(trace.turns()).isEmpty();
    }

    @Test
    void streamChatDispatchesToolUseOnVirtualThreadWhenModelEventArrives() {
        AtomicBoolean toolRanOnVirtualThread = new AtomicBoolean(false);
        AtomicInteger modelCalls = new AtomicInteger();
        InMemoryAgentOrchestrationService service = new InMemoryAgentOrchestrationService(
                (requestId, request, consumer) -> {
                    if (modelCalls.incrementAndGet() == 1) {
                        consumer.accept(AgentModelStreamEvent.token("checking "));
                        consumer.accept(AgentModelStreamEvent.toolUse(
                                "recommend_candidates",
                                Map.of("limit", 2)
                        ));
                        consumer.accept(AgentModelStreamEvent.token("SHOULD_NOT_BE_CONSUMED"));
                        return;
                    }
                    consumer.accept(AgentModelStreamEvent.token("then answering"));
                    consumer.accept(AgentModelStreamEvent.done());
                },
                new VirtualThreadAgentToolUseExecutor(event -> {
                    toolRanOnVirtualThread.set(Thread.currentThread().isVirtual());
                    return Map.of("status", "SUCCESS");
                })
        );
        List<AgentStreamEventVO> events = new ArrayList<>();

        service.streamChat(new AgentChatRequestDTO(
                "sess_stream_tool",
                "A1XYZ",
                "Find a commuter backpack",
                2,
                Map.of("scene", "chat")
        ), events::add);

        assertThat(toolRanOnVirtualThread).isTrue();
        assertThat(modelCalls).hasValue(2);
        assertThat(events).extracting(AgentStreamEventVO::event)
                .containsSubsequence("token", "tool_use", "tool_result", "token", "done");
        assertThat(events.stream()
                .filter(event -> "tool_use".equals(event.event()))
                .findFirst()
                .orElseThrow()
                .data())
                .containsEntry("tool_name", "recommend_candidates");
        assertThat(service.sessionTurns("sess_stream_tool").turns().getFirst().assistantMessage())
                .isEqualTo("checking then answering");
    }

    @Test
    void streamChatFeedsToolResultBackIntoNextModelLoopIteration() {
        AtomicInteger modelCalls = new AtomicInteger();
        AtomicReference<Map<String, Object>> secondLoopContext = new AtomicReference<>();
        InMemoryAgentOrchestrationService service = new InMemoryAgentOrchestrationService(
                (requestId, request, consumer) -> {
                    if (modelCalls.incrementAndGet() == 1) {
                        consumer.accept(AgentModelStreamEvent.toolUse(
                                "recommend_candidates",
                                Map.of("limit", 2)
                        ));
                        consumer.accept(AgentModelStreamEvent.token("SHOULD_NOT_BE_CONSUMED"));
                        return;
                    }
                    secondLoopContext.set(request.resolvedContext());
                    consumer.accept(AgentModelStreamEvent.token("final answer"));
                    consumer.accept(AgentModelStreamEvent.done());
                },
                new VirtualThreadAgentToolUseExecutor(event -> Map.of(
                        "status", "SUCCESS",
                        "items", List.of("B001", "B002")
                ))
        );
        List<AgentStreamEventVO> events = new ArrayList<>();

        service.streamChat(new AgentChatRequestDTO(
                "sess_loop",
                "A1XYZ",
                "Find a commuter backpack",
                2,
                Map.of("scene", "chat")
        ), events::add);

        assertThat(modelCalls).hasValue(2);
        assertThat(secondLoopContext.get()).containsKey("tool_results");
        assertThat((List<?>) secondLoopContext.get().get("tool_results")).hasSize(1);
        assertThat(events).extracting(AgentStreamEventVO::event)
                .containsSubsequence("tool_use", "tool_result", "token", "done");
        assertThat(service.sessionTurns("sess_loop").turns().getFirst().assistantMessage())
                .isEqualTo("final answer");
    }

    @Test
    void streamChatReportsAgentEventsWithStableToolCallIds() {
        List<AgentTraceEventVO> reportedEvents = new ArrayList<>();
        AtomicInteger modelCalls = new AtomicInteger();
        InMemoryAgentOrchestrationService service = new InMemoryAgentOrchestrationService(
                (requestId, request, consumer) -> {
                    if (modelCalls.incrementAndGet() > 1) {
                        consumer.accept(AgentModelStreamEvent.done());
                        return;
                    }
                    consumer.accept(AgentModelStreamEvent.toolUse(
                            "call_001",
                            "recommend_candidates",
                            Map.of("limit", 2)
                    ));
                },
                new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                new InMemoryAgentRuntimeConfigurationService(),
                reportedEvents::add
        );

        service.streamChat(new AgentChatRequestDTO(
                "sess_report",
                "A1XYZ",
                "Find headphones",
                2,
                Map.of("scene", "chat")
        ), ignored -> {
        });

        assertThat(reportedEvents).extracting(AgentTraceEventVO::eventType)
                .contains("agent_started", "tool_use", "tool_result", "agent_done");
        assertThat(reportedEvents).allSatisfy(event -> {
            assertThat(event.phase()).isNotBlank();
            assertThat(event.status()).isNotBlank();
            assertThat(event.inputSummary()).isNotNull();
            assertThat(event.outputSummary()).isNotNull();
        });
        assertThat(reportedEvents).anySatisfy(event -> {
            assertThat(event.eventType()).isEqualTo("tool_result");
            assertThat(event.sessionId()).isEqualTo("sess_report");
            assertThat(event.toolCallId()).isEqualTo("call_001");
            assertThat(event.toolName()).isEqualTo("recommend_candidates");
            assertThat(event.phase()).isEqualTo("recommend");
            assertThat(event.status()).isEqualTo("success");
            assertThat(event.outputSummary()).isEqualTo("status=SUCCESS");
            assertThat(event.data()).containsEntry("status", "SUCCESS");
        });
        assertThat(reportedEvents).anySatisfy(event -> {
            assertThat(event.eventType()).isEqualTo("agent_done");
            assertThat(event.phase()).isEqualTo("final_answer");
            assertThat(event.status()).isEqualTo("success");
        });
    }

    @Test
    void streamChatInfersRagPhaseBeforeRecommendForHybridToolName() {
        List<AgentTraceEventVO> reportedEvents = new ArrayList<>();
        AtomicInteger modelCalls = new AtomicInteger();
        InMemoryAgentOrchestrationService service = new InMemoryAgentOrchestrationService(
                (requestId, request, consumer) -> {
                    if (modelCalls.incrementAndGet() > 1) {
                        consumer.accept(AgentModelStreamEvent.done());
                        return;
                    }
                    consumer.accept(AgentModelStreamEvent.toolUse(
                            "call_rag_001",
                            "recommend_rag_support",
                            Map.of("query", "waterproof commuter bag")
                    ));
                },
                new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                new InMemoryAgentRuntimeConfigurationService(),
                reportedEvents::add
        );

        service.streamChat(new AgentChatRequestDTO(
                "sess_report_rag",
                "A1XYZ",
                "Find waterproof bags",
                2,
                Map.of("scene", "chat")
        ), ignored -> {
        });

        assertThat(reportedEvents).anySatisfy(event -> {
            assertThat(event.eventType()).isEqualTo("tool_result");
            assertThat(event.toolName()).isEqualTo("recommend_rag_support");
            assertThat(event.phase()).isEqualTo("rag");
        });
    }

    @Test
    void streamChatNormalizesTraceFieldsFromReportedEventData() {
        List<AgentTraceEventVO> reportedEvents = new ArrayList<>();
        String longArguments = "argument-".repeat(40);
        String longOutput = "output-".repeat(50);
        InMemoryAgentOrchestrationService service = new InMemoryAgentOrchestrationService(
                new RsAgentLoop(
                        new InMemoryAgentRuntimeConfigurationService(),
                        new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                        (requestId, request, consumer) -> {
                        }
                ) {
                    @Override
                    public AgentLoopResult run(AgentChatRequestDTO request, java.util.function.Consumer<AgentStreamEventVO> consumer, Runnable onReady) {
                        onReady.run();
                        String requestId = "agent_req_normalized";
                        consumer.accept(new AgentStreamEventVO("tool_result", requestId, Map.of(
                                "tool_call_id", "call_query",
                                "tool_name", "recommend_candidates",
                                "latency_ms", 42L,
                                "query", "wireless headphones",
                                "status", "SUCCESS",
                                "output_summary", "ranked 2 candidates"
                        )));
                        consumer.accept(new AgentStreamEventVO("tool_result", requestId, Map.of(
                                "tool_call_id", "call_arguments",
                                "tool_name", "catalog_lookup",
                                "tool_arguments", longArguments,
                                "output_summary", longOutput,
                                "status", "SUCCESS"
                        )));
                        consumer.accept(new AgentStreamEventVO("tool_result", requestId, Map.of(
                                "tool_call_id", "call_error",
                                "tool_name", "catalog_lookup",
                                "status", "ERROR",
                                "error_code", "CATALOG_TIMEOUT",
                                "error_message", "Catalog lookup timed out"
                        )));
                        consumer.accept(new AgentStreamEventVO("tool_result", requestId, Map.of(
                                "tool_call_id", "call_failed",
                                "tool_name", "catalog_lookup",
                                "status", "FAILED"
                        )));
                        consumer.accept(new AgentStreamEventVO("tool_result", requestId, Map.of(
                                "tool_call_id", "call_blank_error",
                                "tool_name", "catalog_lookup",
                                "status", "SUCCESS",
                                "error_code", " ",
                                "error_message", ""
                        )));
                        consumer.accept(new AgentStreamEventVO("done", requestId, Map.of()));
                        return new AgentLoopResult("rs_agent", requestId, "normalized answer", List.of());
                    }
                },
                reportedEvents::add
        );

        service.streamChat(new AgentChatRequestDTO(
                "sess_normalized",
                "A1XYZ",
                "Find wireless headphones",
                2,
                Map.of("scene", "chat")
        ), ignored -> {
        });

        assertThat(reportedEvents).anySatisfy(event -> {
            assertThat(event.eventType()).isEqualTo("tool_result");
            assertThat(event.toolCallId()).isEqualTo("call_query");
            assertThat(event.latencyMs()).isEqualTo(42L);
            assertThat(event.inputSummary()).isEqualTo("query=wireless headphones");
            assertThat(event.outputSummary()).isEqualTo("ranked 2 candidates");
            assertThat(event.errorCode()).isEmpty();
            assertThat(event.errorMessage()).isEmpty();
            assertThat(event.status()).isEqualTo("success");
        });
        assertThat(reportedEvents).anySatisfy(event -> {
            assertThat(event.eventType()).isEqualTo("tool_result");
            assertThat(event.toolCallId()).isEqualTo("call_arguments");
            assertThat(event.inputSummary()).isEqualTo(longArguments.substring(0, 240));
            assertThat(event.outputSummary()).isEqualTo(longOutput.substring(0, 240));
        });
        assertThat(reportedEvents).anySatisfy(event -> {
            assertThat(event.eventType()).isEqualTo("tool_result");
            assertThat(event.toolCallId()).isEqualTo("call_error");
            assertThat(event.status()).isEqualTo("error");
            assertThat(event.errorCode()).isEqualTo("CATALOG_TIMEOUT");
            assertThat(event.errorMessage()).isEqualTo("Catalog lookup timed out");
            assertThat(event.outputSummary()).isEqualTo("status=ERROR");
        });
        assertThat(reportedEvents).anySatisfy(event -> {
            assertThat(event.eventType()).isEqualTo("tool_result");
            assertThat(event.toolCallId()).isEqualTo("call_failed");
            assertThat(event.status()).isEqualTo("error");
            assertThat(event.outputSummary()).isEqualTo("status=FAILED");
        });
        assertThat(reportedEvents).anySatisfy(event -> {
            assertThat(event.eventType()).isEqualTo("tool_result");
            assertThat(event.toolCallId()).isEqualTo("call_blank_error");
            assertThat(event.status()).isEqualTo("success");
            assertThat(event.errorCode()).isEqualTo(" ");
            assertThat(event.errorMessage()).isEmpty();
            assertThat(event.outputSummary()).isEqualTo("status=SUCCESS");
        });
    }

    @Test
    void streamChatInjectsRuntimePromptSkillsAndAgentsIntoModelContext() {
        AtomicReference<Map<String, Object>> modelContext = new AtomicReference<>();
        InMemoryAgentRuntimeConfigurationService runtimeConfigurationService =
                new InMemoryAgentRuntimeConfigurationService();
        runtimeConfigurationService.updateSystemPrompt(new AgentRuntimeSystemPromptUpdateDTO(
                "experiment-a",
                "Use configured prompt."
        ));
        InMemoryAgentOrchestrationService service = new InMemoryAgentOrchestrationService(
                (requestId, request, consumer) -> {
                    modelContext.set(request.resolvedContext());
                    consumer.accept(AgentModelStreamEvent.token("configured answer"));
                    consumer.accept(AgentModelStreamEvent.done());
                },
                new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                runtimeConfigurationService
        );

        service.streamChat(new AgentChatRequestDTO(
                "sess_runtime",
                "A1XYZ",
                "Find a commuter backpack",
                2,
                Map.of("scene", "chat")
        ), ignored -> {
        });

        assertThat(modelContext.get()).containsEntry("system_prompt", "Use configured prompt.");
        assertThat((List<?>) modelContext.get().get("available_skills")).isNotEmpty();
        assertThat((List<?>) modelContext.get().get("available_tools")).isNotEmpty();
        assertThat((List<?>) modelContext.get().get("runtime_context_messages"))
                .anySatisfy(message -> assertThat((String) message)
                        .contains("以下 skill 可以通过 load_skill 工具按需加载："))
                .anySatisfy(message -> assertThat((String) message)
                        .contains("以下 agent 可以通过 call_agent 工具调用："));
        assertThat((List<?>) modelContext.get().get("runtime_context_messages"))
                .noneSatisfy(message -> assertThat((String) message)
                        .contains("以下扩展工具可用："));
        assertThat(modelContext.get()).containsEntry("scene", "chat");
    }

    @Test
    void streamChatCheckpointsTurnEventsIntoHotSessionStore() {
        InMemoryAgentHotSessionStore hotSessionStore = new InMemoryAgentHotSessionStore();
        InMemoryAgentOrchestrationService service = new InMemoryAgentOrchestrationService(
                new RsAgentLoop(
                        new InMemoryAgentRuntimeConfigurationService(),
                        new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                        (requestId, request, consumer) -> {
                            consumer.accept(AgentModelStreamEvent.token("hot answer"));
                            consumer.accept(AgentModelStreamEvent.done());
                        }
                ),
                event -> {
                },
                hotSessionStore
        );

        service.streamChat(new AgentChatRequestDTO(
                "sess_hot_context",
                "A1XYZ",
                "Find wireless headphones",
                2,
                Map.of("scene", "chat")
        ), ignored -> {
        });

        assertThat(hotSessionStore.events("sess_hot_context"))
                .extracting(AgentSessionEvent::eventType)
                .containsExactly("USER_MESSAGE", "ASSISTANT_FINAL");
        assertThat(hotSessionStore.events("sess_hot_context"))
                .anySatisfy(event -> {
                    assertThat(event.eventType()).isEqualTo("USER_MESSAGE");
                    assertThat(event.payload()).containsEntry("content", "Find wireless headphones");
                })
                .anySatisfy(event -> {
                    assertThat(event.eventType()).isEqualTo("ASSISTANT_FINAL");
                    assertThat(event.payload()).containsEntry("assistant_message", "hot answer");
                });
        assertThat(hotSessionStore.latestSnapshot("sess_hot_context"))
                .hasValueSatisfying(snapshot -> {
                    assertThat(snapshot.summaryPayload()).containsEntry("last_user_message", "Find wireless headphones");
                    assertThat(snapshot.summaryPayload()).containsEntry("last_assistant_message", "hot answer");
                    assertThat(snapshot.sourceEventCount()).isEqualTo(hotSessionStore.events("sess_hot_context").size());
                });
    }

    @Test
    void streamChatInjectsLatestHotSessionSnapshotIntoNextTurnContext() {
        InMemoryAgentHotSessionStore hotSessionStore = new InMemoryAgentHotSessionStore();
        AtomicInteger modelCalls = new AtomicInteger();
        AtomicReference<Map<String, Object>> secondTurnContext = new AtomicReference<>();
        InMemoryAgentOrchestrationService service = new InMemoryAgentOrchestrationService(
                new RsAgentLoop(
                        new InMemoryAgentRuntimeConfigurationService(),
                        new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                        (requestId, request, consumer) -> {
                            if (modelCalls.incrementAndGet() == 2) {
                                secondTurnContext.set(request.resolvedContext());
                            }
                            consumer.accept(AgentModelStreamEvent.token("answer-" + modelCalls.get()));
                            consumer.accept(AgentModelStreamEvent.done());
                        }
                ),
                event -> {
                },
                hotSessionStore
        );

        AgentChatRequestDTO firstTurn = new AgentChatRequestDTO(
                "sess_hot_resume",
                "A1XYZ",
                "I want wireless headphones",
                2,
                Map.of("scene", "chat")
        );
        AgentChatRequestDTO secondTurn = new AgentChatRequestDTO(
                "sess_hot_resume",
                "A1XYZ",
                "Anything with noise cancelling?",
                2,
                Map.of("scene", "chat")
        );

        service.streamChat(firstTurn, ignored -> {
        });
        service.streamChat(secondTurn, ignored -> {
        });

        assertThat(secondTurnContext.get()).containsKey("session_hot_context");
        @SuppressWarnings("unchecked")
        Map<String, Object> hotContext = (Map<String, Object>) secondTurnContext.get().get("session_hot_context");
        assertThat(hotContext)
                .containsEntry("last_user_message", "I want wireless headphones")
                .containsEntry("last_assistant_message", "answer-1");
    }

    @Test
    void traceKeepsProfileAndProjectionMetadataWithoutAnswerPayload() {
        List<AgentTraceEventVO> reportedEvents = new ArrayList<>();
        InMemoryAgentOrchestrationService service = new InMemoryAgentOrchestrationService(
                (requestId, request, consumer) -> consumer.accept(AgentModelStreamEvent.toolUse(
                        "emit_final_answer",
                        Map.of("blocks", List.of(Map.of(
                                "type", "text",
                                "content", "不可进入 trace 的回答正文",
                                "diagnostics", Map.of("raw_path", "/secret")
                        )))
                )),
                new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS")),
                new InMemoryAgentRuntimeConfigurationService(),
                reportedEvents::add
        );

        service.streamChat(new AgentChatRequestDTO("sess_trace_projection", "A1XYZ", "Find a bag", 2, Map.of()), ignored -> {
        });

        AgentTraceEventVO answerBlock = reportedEvents.stream()
                .filter(event -> "answer_block".equals(event.eventType()))
                .findFirst()
                .orElseThrow();
        assertThat(answerBlock.data())
                .containsEntry("profile_id", "shopping-assistant")
                .containsEntry("projection_result", "allowed")
                .doesNotContainKeys("content", "diagnostics", "raw_path");
    }

}
