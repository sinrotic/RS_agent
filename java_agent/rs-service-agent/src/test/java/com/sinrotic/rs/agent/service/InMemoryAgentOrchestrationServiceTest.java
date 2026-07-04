package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSystemPromptUpdateDTO;
import com.sinrotic.rs.agent.domain.vo.AgentChatVO;
import com.sinrotic.rs.agent.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.agent.service.impl.AgentLoopResult;
import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
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
    void chatStoresTurnForSessionTrace() {
        InMemoryAgentOrchestrationService service = new InMemoryAgentOrchestrationService();

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
                .containsExactly("recommend_candidates", "rag_support", "model_chat");
        assertThat(trace.turns()).hasSize(1);
        assertThat(trace.turns().getFirst().requestId()).isEqualTo(chat.requestId());
        assertThat(trace.turns().getFirst().recommendedItemIds()).containsExactly("B001", "B002");
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
                .containsSequence("token", "tool_use", "tool_result", "token", "done");
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
                .containsSequence("tool_use", "tool_result", "token", "done");
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
                    public AgentLoopResult run(AgentChatRequestDTO request, java.util.function.Consumer<AgentStreamEventVO> consumer) {
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
}
