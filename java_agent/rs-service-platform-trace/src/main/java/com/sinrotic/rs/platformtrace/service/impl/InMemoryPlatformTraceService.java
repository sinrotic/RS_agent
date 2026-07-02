package com.sinrotic.rs.platformtrace.service.impl;

import com.sinrotic.rs.platformtrace.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentRunEventVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentRunMonitorVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentRunPhaseVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentRunRelatedTraceVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentRunSummaryVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentTraceEventsVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformAccountProfileVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformInteractionEventVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformSessionOverviewVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformTimelineEventVO;
import com.sinrotic.rs.platformtrace.domain.vo.RecommendTraceVO;
import com.sinrotic.rs.platformtrace.service.PlatformTraceService;
import com.sinrotic.rs.platformtrace.service.client.NoopPlatformTraceDownstreamClient;
import com.sinrotic.rs.platformtrace.service.client.PlatformTraceDownstreamClient;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.Comparator;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

@Service
public class InMemoryPlatformTraceService implements PlatformTraceService {

    private final PlatformTraceDownstreamClient downstreamClient;
    private final Map<String, PlatformAccountProfileVO> accountProfiles = new ConcurrentHashMap<>();
    private final Map<String, RecommendTraceVO> recommendTraces = new ConcurrentHashMap<>();
    private final Map<String, AgentSessionTraceVO> agentSessionTraces = new ConcurrentHashMap<>();
    private final Map<String, List<AgentTraceEventVO>> agentEventsByRequestId = new ConcurrentHashMap<>();
    private final Map<String, List<AgentTraceEventVO>> agentEventsBySessionId = new ConcurrentHashMap<>();
    private final Map<String, List<PlatformInteractionEventVO>> interactionEventsBySessionId = new ConcurrentHashMap<>();

    public InMemoryPlatformTraceService() {
        this(new NoopPlatformTraceDownstreamClient());
    }

    @Autowired
    public InMemoryPlatformTraceService(PlatformTraceDownstreamClient downstreamClient) {
        this.downstreamClient = downstreamClient;
    }

    @Override
    public PlatformAccountProfileVO accountProfile(String accountId) {
        PlatformAccountProfileVO cached = accountProfiles.get(accountId);
        if (cached != null) {
            return cached;
        }
        Optional<PlatformAccountProfileVO> fetched = downstreamClient.fetchAccountProfile(accountId);
        fetched.ifPresent(this::saveAccountProfile);
        return fetched.orElseGet(() -> PlatformAccountProfileVO.empty(accountId));
    }

    @Override
    public RecommendTraceVO recommendTrace(String requestId) {
        RecommendTraceVO cached = recommendTraces.get(requestId);
        if (cached != null) {
            return cached;
        }
        Optional<RecommendTraceVO> fetched = downstreamClient.fetchRecommendTrace(requestId);
        fetched.ifPresent(this::saveRecommendTrace);
        return fetched.orElseGet(() -> RecommendTraceVO.empty(requestId));
    }

    @Override
    public AgentSessionTraceVO agentSessionTurns(String sessionId) {
        AgentSessionTraceVO cached = agentSessionTraces.get(sessionId);
        if (cached != null) {
            return cached;
        }
        Optional<AgentSessionTraceVO> fetched = downstreamClient.fetchAgentSessionTrace(sessionId);
        fetched.ifPresent(this::saveAgentSessionTrace);
        return fetched.orElseGet(() -> AgentSessionTraceVO.empty(sessionId));
    }

    @Override
    public AgentTraceEventsVO agentRequestEvents(String requestId) {
        return new AgentTraceEventsVO(requestId, snapshot(agentEventsByRequestId.getOrDefault(requestId, List.of())));
    }

    @Override
    public AgentRunMonitorVO agentRequestMonitor(String requestId) {
        if (!hasText(requestId)) {
            return AgentRunMonitorVO.empty("", requestId);
        }
        List<AgentTraceEventVO> events = sortedAgentEvents(agentEventsByRequestId.getOrDefault(requestId, List.of()));
        if (events.isEmpty()) {
            return AgentRunMonitorVO.empty("", requestId);
        }
        String sessionId = events.stream()
                .map(AgentTraceEventVO::sessionId)
                .filter(this::hasText)
                .findFirst()
                .orElse("");
        return buildAgentRunMonitor(sessionId, requestId, requestId, events);
    }

    @Override
    public AgentRunMonitorVO agentSessionMonitor(String sessionId, String requestId) {
        if (!hasText(sessionId)) {
            return AgentRunMonitorVO.empty(sessionId, requestId);
        }
        List<AgentTraceEventVO> events = sortedAgentEvents(agentEventsBySessionId.getOrDefault(sessionId, List.of()).stream()
                .filter(event -> !hasText(requestId) || requestId.equals(event.requestId()))
                .toList());
        if (events.isEmpty()) {
            return AgentRunMonitorVO.empty(sessionId, requestId);
        }
        String monitorRequestId = hasText(requestId)
                ? requestId
                : events.stream()
                .map(AgentTraceEventVO::requestId)
                .filter(this::hasText)
                .reduce((ignored, latest) -> latest)
                .orElse("");
        return buildAgentRunMonitor(sessionId, monitorRequestId, requestId, events);
    }

    @Override
    public List<PlatformInteractionEventVO> interactionEvents(String sessionId) {
        return snapshot(interactionEventsBySessionId.getOrDefault(sessionId, List.of())).stream()
                .sorted(Comparator.comparing(PlatformInteractionEventVO::occurredAt))
                .toList();
    }

    @Override
    public List<PlatformTimelineEventVO> sessionTimeline(String sessionId) {
        List<PlatformTimelineEventVO> timeline = new ArrayList<>();
        interactionEvents(sessionId).stream()
                .map(this::toTimelineEvent)
                .forEach(timeline::add);
        snapshot(agentEventsBySessionId.getOrDefault(sessionId, List.of())).stream()
                .map(this::toTimelineEvent)
                .forEach(timeline::add);
        return timeline.stream()
                .sorted(Comparator.comparing(PlatformTimelineEventVO::occurredAt))
                .toList();
    }

    @Override
    public PlatformSessionOverviewVO sessionOverview(String sessionId, String accountId, String requestId) {
        PlatformAccountProfileVO profile = hasText(accountId)
                ? accountProfile(accountId)
                : PlatformAccountProfileVO.empty("");
        AgentSessionTraceVO agentTrace = agentSessionTurns(sessionId);
        List<RecommendTraceVO> sessionRecommendTraces = recommendTraces.values().stream()
                .filter(trace -> sessionId.equals(trace.sessionId()))
                .sorted(Comparator.comparing(RecommendTraceVO::requestId))
                .toList();
        if (hasText(requestId) && sessionRecommendTraces.stream().noneMatch(trace -> requestId.equals(trace.requestId()))) {
            RecommendTraceVO requestedTrace = recommendTrace(requestId);
            if (hasText(requestedTrace.requestId())) {
                sessionRecommendTraces = new java.util.ArrayList<>(sessionRecommendTraces);
                sessionRecommendTraces.add(requestedTrace);
            }
        }
        return new PlatformSessionOverviewVO(
                sessionId,
                profile,
                agentTrace,
                sessionRecommendTraces,
                interactionEvents(sessionId),
                sessionTimeline(sessionId)
        );
    }

    @Override
    public void saveAccountProfile(PlatformAccountProfileVO profile) {
        if (profile != null && hasText(profile.accountId())) {
            accountProfiles.put(profile.accountId(), profile);
        }
    }

    @Override
    public void saveRecommendTrace(RecommendTraceVO trace) {
        if (trace != null && hasText(trace.requestId())) {
            recommendTraces.put(trace.requestId(), trace);
        }
    }

    @Override
    public void saveAgentSessionTrace(AgentSessionTraceVO trace) {
        if (trace != null && hasText(trace.sessionId())) {
            agentSessionTraces.put(trace.sessionId(), trace);
        }
    }

    @Override
    public AgentTraceEventVO saveAgentTraceEvent(AgentTraceEventVO event) {
        if (event == null || !hasText(event.requestId())) {
            return event;
        }
        AgentTraceEventVO stored = new AgentTraceEventVO(
                hasText(event.eventId()) ? event.eventId() : "evt_" + java.util.UUID.randomUUID().toString().substring(0, 8),
                event.sessionId(),
                event.requestId(),
                event.eventType(),
                event.phase(),
                event.status(),
                event.toolCallId(),
                event.toolName(),
                event.agentName(),
                event.modelProvider(),
                event.modelName(),
                event.latencyMs(),
                event.promptTokens(),
                event.completionTokens(),
                event.totalTokens(),
                event.cacheReadInputTokens(),
                event.cacheWriteInputTokens(),
                event.errorCode(),
                event.errorMessage(),
                event.inputSummary(),
                event.outputSummary(),
                event.data(),
                event.createdAt()
        );
        agentEventsByRequestId.computeIfAbsent(stored.requestId(), ignored -> new CopyOnWriteArrayList<>()).add(stored);
        if (hasText(stored.sessionId())) {
            agentEventsBySessionId.computeIfAbsent(stored.sessionId(), ignored -> new CopyOnWriteArrayList<>()).add(stored);
        }
        return stored;
    }

    @Override
    public PlatformInteractionEventVO saveInteractionEvent(PlatformInteractionEventVO event) {
        if (event == null || !hasText(event.sessionId())) {
            return event;
        }
        PlatformInteractionEventVO stored = new PlatformInteractionEventVO(
                hasText(event.eventId()) ? event.eventId() : "evt_" + java.util.UUID.randomUUID().toString().substring(0, 8),
                event.sessionId(),
                event.requestId(),
                event.itemId(),
                event.eventType(),
                event.eventValue(),
                event.occurredAt(),
                event.metadata()
        );
        interactionEventsBySessionId.computeIfAbsent(stored.sessionId(), ignored -> new CopyOnWriteArrayList<>()).add(stored);
        return stored;
    }

    private AgentRunMonitorVO buildAgentRunMonitor(
            String sessionId,
            String requestId,
            String recommendScopeRequestId,
            List<AgentTraceEventVO> sourceEvents
    ) {
        List<AgentRunEventVO> events = sourceEvents.stream()
                .map(this::toRunEvent)
                .toList();
        int recommendItemCount = recommendItemCount(sessionId, recommendScopeRequestId);
        boolean hasFinalAnswer = events.stream().anyMatch(this::hasFinalAnswer);
        boolean hasError = events.stream().anyMatch(this::isErrorEvent);
        long totalLatencyMs = events.stream().mapToLong(event -> event.latencyMs() == null ? 0L : event.latencyMs()).sum();
        int promptTokens = events.stream().mapToInt(event -> event.promptTokens() == null ? 0 : event.promptTokens()).sum();
        int completionTokens = events.stream().mapToInt(event -> event.completionTokens() == null ? 0 : event.completionTokens()).sum();
        int totalTokens = events.stream().mapToInt(event -> event.totalTokens() == null ? 0 : event.totalTokens()).sum();
        int toolCallCount = toolCallCount(events);
        int errorCount = (int) events.stream().filter(this::isErrorEvent).count();
        AgentRunSummaryVO summary = new AgentRunSummaryVO(
                totalLatencyMs,
                promptTokens,
                completionTokens,
                totalTokens,
                firstText(events.stream().map(AgentRunEventVO::modelProvider).toList()),
                firstText(events.stream().map(AgentRunEventVO::modelName).toList()),
                toolCallCount,
                errorCount,
                recommendItemCount,
                hasFinalAnswer
        );
        return new AgentRunMonitorVO(
                sessionId,
                requestId,
                overallStatus(events, hasError, hasFinalAnswer),
                summary,
                phases(events),
                events,
                qualitySignals(events, summary),
                relatedTraces(sessionId, recommendScopeRequestId)
        );
    }

    private List<AgentRunPhaseVO> phases(List<AgentRunEventVO> events) {
        Map<String, PhaseAccumulator> phases = new LinkedHashMap<>();
        for (AgentRunEventVO event : events) {
            phases.computeIfAbsent(event.phase(), ignored -> new PhaseAccumulator()).add(event);
        }
        return phases.entrySet().stream()
                .map(entry -> entry.getValue().toPhase(entry.getKey()))
                .toList();
    }

    private int toolCallCount(List<AgentRunEventVO> events) {
        Set<String> toolCallIds = new LinkedHashSet<>();
        int legacyToolEvents = 0;
        for (AgentRunEventVO event : events) {
            if (!isToolContext(event)) {
                continue;
            }
            if (hasText(event.toolCallId())) {
                toolCallIds.add(event.toolCallId());
            } else {
                legacyToolEvents++;
            }
        }
        return toolCallIds.size() + legacyToolEvents;
    }

    private List<String> qualitySignals(List<AgentRunEventVO> events, AgentRunSummaryVO summary) {
        Set<String> signals = new LinkedHashSet<>();
        if (!summary.hasFinalAnswer()) {
            signals.add("missing_final_answer");
        }
        if (events.stream().anyMatch(event -> isErrorEvent(event) && isToolContext(event))) {
            signals.add("tool_error");
        }
        if (events.stream().anyMatch(event -> isErrorEvent(event) && isModelContext(event))) {
            signals.add("model_error");
        }
        if (summary.totalLatencyMs() > 10_000L) {
            signals.add("high_latency");
        }
        if (events.stream().anyMatch(this::isEmptySuccessfulToolResult)) {
            signals.add("empty_tool_result");
        }
        boolean hasRecommendPhase = events.stream().anyMatch(event -> "recommend".equals(event.phase()));
        if (hasRecommendPhase && summary.recommendItemCount() == 0) {
            signals.add("no_recommendation_items");
        }
        return List.copyOf(signals);
    }

    private AgentRunRelatedTraceVO relatedTraces(String sessionId, String requestId) {
        if (!hasText(sessionId)) {
            return AgentRunRelatedTraceVO.empty();
        }
        int agentTurnCount = agentSessionTraces.getOrDefault(sessionId, AgentSessionTraceVO.empty(sessionId)).turns().size();
        List<String> recommendRequestIds = recommendTraces.values().stream()
                .filter(trace -> sessionId.equals(trace.sessionId()))
                .filter(trace -> !hasText(requestId) || requestId.equals(trace.requestId()))
                .map(RecommendTraceVO::requestId)
                .filter(this::hasText)
                .sorted()
                .toList();
        int interactionEventCount = snapshot(interactionEventsBySessionId.getOrDefault(sessionId, List.of())).size();
        return new AgentRunRelatedTraceVO(agentTurnCount, recommendRequestIds, interactionEventCount);
    }

    private int recommendItemCount(String sessionId, String requestId) {
        if (!hasText(sessionId)) {
            return 0;
        }
        return recommendTraces.values().stream()
                .filter(trace -> sessionId.equals(trace.sessionId()))
                .filter(trace -> !hasText(requestId) || requestId.equals(trace.requestId()))
                .mapToInt(trace -> trace.items().size())
                .sum();
    }

    private AgentRunEventVO toRunEvent(AgentTraceEventVO event) {
        return new AgentRunEventVO(
                event.eventId(),
                event.sessionId(),
                event.requestId(),
                event.eventType(),
                inferPhase(event),
                inferStatus(event),
                event.toolCallId(),
                event.toolName(),
                event.agentName(),
                event.modelProvider(),
                event.modelName(),
                event.latencyMs(),
                event.promptTokens(),
                event.completionTokens(),
                event.totalTokens(),
                event.errorCode(),
                event.errorMessage(),
                event.inputSummary(),
                event.outputSummary(),
                event.data(),
                event.createdAt()
        );
    }

    private String inferPhase(AgentTraceEventVO event) {
        if (hasText(event.phase())) {
            return event.phase();
        }
        String eventType = nullToEmpty(event.eventType()).toLowerCase();
        String toolName = nullToEmpty(event.toolName()).toLowerCase();
        if (hasText(event.toolName())) {
            if (toolName.contains("rag")) {
                return "rag";
            }
            if (toolName.contains("recommend")) {
                return "recommend";
            }
            return "tool_call";
        }
        if (eventType.contains("model")) {
            return "model_call";
        }
        if (eventType.contains("done") || eventType.contains("final")) {
            return "final_answer";
        }
        return "agent";
    }

    private String inferStatus(AgentTraceEventVO event) {
        if (hasErrorEvidence(event.status(), event.errorCode(), event.errorMessage(), event.eventType(), event.data())) {
            return "error";
        }
        if (hasText(event.status())) {
            return event.status();
        }
        return "success";
    }

    private String overallStatus(List<AgentRunEventVO> events, boolean hasError, boolean hasFinalAnswer) {
        if (hasError) {
            return "failed";
        }
        boolean hasTerminalEvent = events.stream().anyMatch(event -> "agent_done".equals(event.eventType()));
        if (hasTerminalEvent || hasFinalAnswer) {
            return "success";
        }
        return "running";
    }

    private boolean hasFinalAnswer(AgentRunEventVO event) {
        if ("final_answer".equals(event.phase()) || "agent_done".equals(event.eventType())) {
            return true;
        }
        Object value = event.data().get("final_answer_present");
        return Boolean.TRUE.equals(value) || "true".equalsIgnoreCase(String.valueOf(value));
    }

    private boolean isErrorEvent(AgentRunEventVO event) {
        return "error".equalsIgnoreCase(event.status())
                || "failed".equalsIgnoreCase(event.status())
                || hasErrorEvidence(event.status(), event.errorCode(), event.errorMessage(), event.eventType(), event.data());
    }

    private boolean hasErrorEvidence(String status, String errorCode, String errorMessage, String eventType, Map<String, Object> data) {
        String dataStatus = String.valueOf(data.get("status"));
        return "error".equalsIgnoreCase(status)
                || "failed".equalsIgnoreCase(status)
                || hasText(errorCode)
                || hasText(errorMessage)
                || containsText(eventType, "error")
                || "ERROR".equalsIgnoreCase(dataStatus)
                || "FAILED".equalsIgnoreCase(dataStatus);
    }

    private boolean isToolContext(AgentRunEventVO event) {
        return containsText(event.eventType(), "tool")
                || hasText(event.toolName())
                || hasText(event.toolCallId());
    }

    private boolean isModelContext(AgentRunEventVO event) {
        return containsText(event.eventType(), "model")
                || "generation".equals(event.phase());
    }

    private boolean isEmptySuccessfulToolResult(AgentRunEventVO event) {
        return hasText(event.toolName())
                && !isErrorEvent(event)
                && !hasMeaningfulOutput(event);
    }

    private boolean hasMeaningfulOutput(AgentRunEventVO event) {
        return hasText(event.outputSummary())
                || isMeaningfulDataValue(event.data().get("items"))
                || isMeaningfulDataValue(event.data().get("result"))
                || isMeaningfulDataValue(event.data().get("output"))
                || isMeaningfulDataValue(event.data().get("content"));
    }

    private boolean isMeaningfulDataValue(Object value) {
        if (value == null) {
            return false;
        }
        if (value instanceof String stringValue) {
            return hasText(stringValue);
        }
        if (value instanceof java.util.Collection<?> collectionValue) {
            return !collectionValue.isEmpty();
        }
        if (value instanceof Map<?, ?> mapValue) {
            return !mapValue.isEmpty();
        }
        return true;
    }

    private List<AgentTraceEventVO> sortedAgentEvents(List<AgentTraceEventVO> events) {
        return snapshot(events).stream()
                .sorted(Comparator.comparing(AgentTraceEventVO::createdAt))
                .toList();
    }

    private <T> List<T> snapshot(List<T> values) {
        return List.copyOf(values);
    }

    private PlatformTimelineEventVO toTimelineEvent(PlatformInteractionEventVO event) {
        return new PlatformTimelineEventVO(
                event.eventId(),
                event.sessionId(),
                event.requestId(),
                event.eventType(),
                "interaction",
                event.itemId(),
                event.eventType() + " " + nullToEmpty(event.itemId()),
                event.occurredAt(),
                Map.of(
                        "item_id", nullToEmpty(event.itemId()),
                        "event_value", event.eventValue() == null ? "" : event.eventValue(),
                        "metadata", event.metadata()
                )
        );
    }

    private PlatformTimelineEventVO toTimelineEvent(AgentTraceEventVO event) {
        return new PlatformTimelineEventVO(
                event.eventId(),
                event.sessionId(),
                event.requestId(),
                event.eventType(),
                "agent",
                event.toolCallId(),
                event.toolName(),
                event.createdAt(),
                Map.of(
                        "tool_name", nullToEmpty(event.toolName()),
                        "agent_name", nullToEmpty(event.agentName()),
                        "latency_ms", event.latencyMs() == null ? "" : event.latencyMs(),
                        "prompt_tokens", event.promptTokens() == null ? "" : event.promptTokens(),
                        "completion_tokens", event.completionTokens() == null ? "" : event.completionTokens(),
                        "total_tokens", event.totalTokens() == null ? "" : event.totalTokens(),
                        "data", event.data()
                )
        );
    }

    private String nullToEmpty(String value) {
        return value == null ? "" : value;
    }

    private String firstText(List<String> values) {
        return values.stream()
                .filter(this::hasText)
                .findFirst()
                .orElse("");
    }

    private boolean containsText(String value, String expected) {
        return value != null && value.toLowerCase().contains(expected.toLowerCase());
    }

    private boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private static class PhaseAccumulator {
        private int eventCount;
        private long latencyMs;
        private int totalTokens;
        private boolean hasError;

        void add(AgentRunEventVO event) {
            eventCount++;
            latencyMs += event.latencyMs() == null ? 0L : event.latencyMs();
            totalTokens += event.totalTokens() == null ? 0 : event.totalTokens();
            hasError = hasError
                    || "error".equalsIgnoreCase(event.status())
                    || "failed".equalsIgnoreCase(event.status())
                    || event.errorCode() != null && !event.errorCode().isBlank();
        }

        AgentRunPhaseVO toPhase(String phase) {
            return new AgentRunPhaseVO(phase, hasError ? "failed" : "success", eventCount, latencyMs, totalTokens);
        }
    }
}
