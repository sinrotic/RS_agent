package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentChatVO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.domain.vo.AgentToolCallVO;
import com.sinrotic.rs.agent.domain.vo.AgentTurnVO;
import com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.agent.service.AgentChatService;
import com.sinrotic.rs.agent.service.AgentChatStreamService;
import com.sinrotic.rs.agent.service.AgentLoopHookDispatcher;
import com.sinrotic.rs.agent.service.AgentInterrupter;
import com.sinrotic.rs.agent.service.AgentModelStreamClient;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.AgentRecommendationService;
import com.sinrotic.rs.agent.service.AgentTraceReporter;
import com.sinrotic.rs.agent.service.AgentToolUseExecutor;
import com.sinrotic.rs.agent.service.AgentTraceService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

@Service
public class InMemoryAgentOrchestrationService implements AgentChatService, AgentChatStreamService, AgentTraceService {

    private final ConcurrentMap<String, List<AgentTurnVO>> sessionTurns = new ConcurrentHashMap<>();

    private final AgentLoop agentLoop;

    private final AgentTraceReporter traceReporter;

    private final AgentRecommendationService recommendationService;

    public InMemoryAgentOrchestrationService() {
        this(
                new MockAgentModelStreamClient(),
                new VirtualThreadAgentToolUseExecutor(),
                new InMemoryAgentRuntimeConfigurationService(),
                event -> {
                },
                new InMemoryAgentRecommendationService()
        );
    }

    public InMemoryAgentOrchestrationService(
            AgentModelStreamClient modelStreamClient,
            AgentToolUseExecutor toolUseExecutor
    ) {
        this(modelStreamClient, toolUseExecutor, new InMemoryAgentRuntimeConfigurationService(), event -> {
        }, new InMemoryAgentRecommendationService());
    }

    @Autowired
    public InMemoryAgentOrchestrationService(
            AgentModelStreamClient modelStreamClient,
            AgentToolUseExecutor toolUseExecutor,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentTraceReporter traceReporter,
            AgentLoopHookDispatcher hookDispatcher,
            AgentInterrupter interrupter,
            AgentRecommendationService recommendationService
    ) {
        this(new RsAgentLoop(runtimeConfigurationService, toolUseExecutor, modelStreamClient, hookDispatcher, interrupter), traceReporter, recommendationService);
    }

    public InMemoryAgentOrchestrationService(
            AgentModelStreamClient modelStreamClient,
            AgentToolUseExecutor toolUseExecutor,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentTraceReporter traceReporter
    ) {
        this(
                modelStreamClient,
                toolUseExecutor,
                runtimeConfigurationService,
                traceReporter,
                new NoopAgentLoopHookDispatcher(),
                new InMemoryAgentInterrupter(),
                new InMemoryAgentRecommendationService()
        );
    }

    public InMemoryAgentOrchestrationService(
            AgentModelStreamClient modelStreamClient,
            AgentToolUseExecutor toolUseExecutor,
            AgentRuntimeConfigurationService runtimeConfigurationService,
            AgentTraceReporter traceReporter,
            AgentRecommendationService recommendationService
    ) {
        this(
                modelStreamClient,
                toolUseExecutor,
                runtimeConfigurationService,
                traceReporter,
                new NoopAgentLoopHookDispatcher(),
                new InMemoryAgentInterrupter(),
                recommendationService
        );
    }

    public InMemoryAgentOrchestrationService(
            AgentModelStreamClient modelStreamClient,
            AgentToolUseExecutor toolUseExecutor,
            AgentRuntimeConfigurationService runtimeConfigurationService
    ) {
        this(modelStreamClient, toolUseExecutor, runtimeConfigurationService, event -> {
        }, new InMemoryAgentRecommendationService());
    }

    public InMemoryAgentOrchestrationService(AgentLoop agentLoop) {
        this(agentLoop, event -> {
        }, new InMemoryAgentRecommendationService());
    }

    public InMemoryAgentOrchestrationService(AgentLoop agentLoop, AgentTraceReporter traceReporter) {
        this(agentLoop, traceReporter, new InMemoryAgentRecommendationService());
    }

    public InMemoryAgentOrchestrationService(
            AgentLoop agentLoop,
            AgentTraceReporter traceReporter,
            AgentRecommendationService recommendationService
    ) {
        this.agentLoop = agentLoop;
        this.traceReporter = traceReporter == null ? event -> {
        } : traceReporter;
        this.recommendationService = recommendationService;
    }

    @Override
    public AgentChatVO chat(AgentChatRequestDTO request) {
        List<AgentRecommendedItemVO> recommendations = recommendationService.recommend(request);
        int limit = recommendations.size();
        List<String> recommendedItemIds = recommendations.stream()
                .map(AgentRecommendedItemVO::itemId)
                .toList();
        String requestId = "agent_req_" + UUID.randomUUID().toString().substring(0, 8);
        List<AgentToolCallVO> toolCalls = toolCalls(limit, request.resolvedContext());
        String assistantMessage = "我会优先推荐通勤背包，并补充可解释证据。";

        AgentTurnVO turn = new AgentTurnVO(
                requestId,
                request.userMessage(),
                assistantMessage,
                toolCalls,
                recommendedItemIds
        );
        sessionTurns.computeIfAbsent(request.sessionId(), ignored -> new ArrayList<>()).add(turn);

        return new AgentChatVO(
                requestId,
                request.sessionId(),
                request.profileUserId(),
                assistantMessage,
                recommendations,
                toolCalls
        );
    }

    @Override
    public void streamChat(AgentChatRequestDTO request, Consumer<AgentStreamEventVO> consumer) {
        List<AgentRecommendedItemVO> recommendations = recommendationService.recommend(request);
        int limit = recommendations.size();
        List<String> recommendedItemIds = recommendations.stream()
                .map(AgentRecommendedItemVO::itemId)
                .toList();
        String requestId = "agent_req_" + UUID.randomUUID().toString().substring(0, 8);
        List<AgentToolCallVO> toolCalls = new ArrayList<>();

        for (AgentToolCallVO toolCall : toolCalls(limit, request.resolvedContext())) {
            toolCalls.add(toolCall);
            consumer.accept(toolTraceEvent(requestId, toolCall));
        }

        AtomicBoolean startedReported = new AtomicBoolean(false);
        AgentLoopResult loopResult = agentLoop.run(request, event -> {
            reportStartedOnce(request, event.requestId(), startedReported);
            reportStreamEvent(request, event);
            if ("done".equals(event.event())) {
                Map<String, Object> doneData = new java.util.LinkedHashMap<>(event.data());
                doneData.put("done", true);
                doneData.put("recommended_item_ids", recommendedItemIds);
                consumer.accept(new AgentStreamEventVO("done", event.requestId(), Map.copyOf(doneData)));
                return;
            }
            consumer.accept(event);
        });
        toolCalls.addAll(loopResult.toolCalls());

        AgentTurnVO turn = new AgentTurnVO(
                loopResult.requestId(),
                request.userMessage(),
                loopResult.assistantMessage(),
                toolCalls,
                recommendedItemIds
        );
        sessionTurns.computeIfAbsent(request.sessionId(), ignored -> new ArrayList<>()).add(turn);
    }

    @Override
    public AgentSessionTraceVO sessionTurns(String sessionId) {
        return new AgentSessionTraceVO(sessionId, List.copyOf(sessionTurns.getOrDefault(sessionId, List.of())));
    }

    @Override
    public AgentSessionTraceVO platformSessionTrace(String sessionId) {
        return sessionTurns(sessionId);
    }

    private List<AgentToolCallVO> toolCalls(int limit, Map<String, Object> context) {
        return List.of(
                new AgentToolCallVO(
                        "recommend_candidates",
                        "rs-service-recommend",
                        "SUCCESS",
                        Map.of("limit", limit, "scene", context.getOrDefault("scene", "agent_chat"))
                ),
                new AgentToolCallVO(
                        "rag_support",
                        "rs-service-recommend",
                        "SUCCESS",
                        Map.of("providers", List.of("elasticsearch_bm25", "milvus_vector"))
                ),
                new AgentToolCallVO(
                        "model_chat",
                        "rs-service-model",
                        "SUCCESS",
                        Map.of("model_key", "agent_4b")
                )
        );
    }

    private AgentStreamEventVO toolTraceEvent(String requestId, AgentToolCallVO toolCall) {
        return new AgentStreamEventVO("trace", requestId, Map.of(
                "tool_call_id", toolCall.toolCallId(),
                "tool_name", toolCall.toolName(),
                "service", toolCall.service(),
                "status", toolCall.status(),
                "metadata", toolCall.metadata()
        ));
    }

    private void reportStartedOnce(AgentChatRequestDTO request, String requestId, AtomicBoolean startedReported) {
        if (startedReported.compareAndSet(false, true)) {
            reportTraceEvent(request, requestId, "agent_started", Map.of(), null, null);
        }
    }

    private void reportStreamEvent(AgentChatRequestDTO request, AgentStreamEventVO event) {
        String eventType = "done".equals(event.event()) ? "agent_done" : event.event();
        reportTraceEvent(request, event.requestId(), eventType, event.data(), stringValue(event.data().get("tool_call_id")),
                stringValue(event.data().get("tool_name")));
    }

    private void reportTraceEvent(
            AgentChatRequestDTO request,
            String requestId,
            String eventType,
            Map<String, Object> data,
            String toolCallId,
            String toolName
    ) {
        Map<String, Object> traceData = publicTraceMetadata(request, eventType, data);
        traceReporter.report(new AgentTraceEventVO(
                "evt_" + UUID.randomUUID().toString().substring(0, 8),
                request.sessionId(),
                requestId,
                eventType,
                toolCallId,
                toolName,
                "rs_agent",
                stringValue(request.resolvedContext().getOrDefault("model_provider", "spring_ai")),
                stringValue(request.resolvedContext().getOrDefault("model_name", "")),
                longValue(traceData.get("latency_ms")),
                integerValue(traceData.get("prompt_tokens")),
                integerValue(traceData.get("completion_tokens")),
                integerValue(traceData.get("total_tokens")),
                longValue(traceData.get("cache_read_input_tokens")),
                longValue(traceData.get("cache_write_input_tokens")),
                inferPhase(eventType, toolName),
                inferStatus(eventType, traceData),
                stringValue(traceData.get("error_code")),
                stringValue(traceData.get("error_message")),
                inputSummary(traceData),
                outputSummary(traceData),
                traceData,
                java.time.Instant.now()
        ));
    }

    private Map<String, Object> publicTraceMetadata(
            AgentChatRequestDTO request,
            String eventType,
            Map<String, Object> data
    ) {
        Map<String, Object> safe = new java.util.LinkedHashMap<>();
        for (String key : List.of(
                "status", "error_code", "error_message", "latency_ms", "prompt_tokens",
                "completion_tokens", "total_tokens", "cache_read_input_tokens", "cache_write_input_tokens",
                "capability_id"
        )) {
            Object value = data.get(key);
            if (value != null) {
                safe.put(key, value);
            }
        }
        Object profileId = data.containsKey("profile_id")
                ? data.get("profile_id")
                : request.resolvedContext().get("agent_profile_id");
        if (profileId instanceof String value && !value.isBlank()) {
            safe.put("profile_id", value);
        }
        if ("answer_block".equals(eventType)) {
            safe.put("projection_result", "allowed");
            Object type = data.get("type");
            if (type instanceof String value && !value.isBlank()) {
                safe.put("output_block_type", value);
            }
        }
        return Map.copyOf(safe);
    }

    private String inferPhase(String eventType, String toolName) {
        if (hasText(toolName)) {
            String normalizedToolName = toolName.toLowerCase(Locale.ROOT);
            if (normalizedToolName.contains("rag")) {
                return "rag";
            }
            if (normalizedToolName.contains("recommend")) {
                return "recommend";
            }
            return "tool_call";
        }

        String normalizedEventType = stringValue(eventType).toLowerCase(Locale.ROOT);
        if (normalizedEventType.contains("model")) {
            return "model_call";
        }
        if (normalizedEventType.contains("done") || normalizedEventType.contains("final")) {
            return "final_answer";
        }
        return "agent";
    }

    private String inferStatus(String eventType, Map<String, Object> data) {
        String dataStatus = stringValue(data.get("status"));
        if (isErrorStatus(dataStatus)
                || hasText(stringValue(data.get("error_code")))
                || hasText(stringValue(data.get("error_message")))
                || stringValue(eventType).toLowerCase(Locale.ROOT).contains("error")) {
            return "error";
        }
        return "success";
    }

    private boolean isErrorStatus(String status) {
        return "ERROR".equalsIgnoreCase(status) || "FAILED".equalsIgnoreCase(status);
    }

    private String inputSummary(Map<String, Object> data) {
        if (data.containsKey("query")) {
            return "query=" + stringValue(data.get("query"));
        }
        if (data.containsKey("tool_arguments")) {
            return truncate(stringValue(data.get("tool_arguments")));
        }
        return "";
    }

    private String outputSummary(Map<String, Object> data) {
        if (data.containsKey("output_summary")) {
            return truncate(stringValue(data.get("output_summary")));
        }
        if (data.containsKey("status")) {
            return "status=" + stringValue(data.get("status"));
        }
        return "";
    }

    private String truncate(String value) {
        return value.length() <= 240 ? value : value.substring(0, 240);
    }

    private boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private String stringValue(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    private Integer integerValue(Object value) {
        if (value instanceof Number number) {
            return number.intValue();
        }
        if (value instanceof String text && !text.isBlank()) {
            try {
                return Integer.parseInt(text);
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }

    private Long longValue(Object value) {
        if (value instanceof Number number) {
            return number.longValue();
        }
        if (value instanceof String text && !text.isBlank()) {
            try {
                return Long.parseLong(text);
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }

}
