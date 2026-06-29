package com.sinrotic.rs.platformtrace.service.impl;

import com.sinrotic.rs.platformtrace.domain.vo.AgentSessionTraceVO;
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
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

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
        return new AgentTraceEventsVO(requestId, List.copyOf(agentEventsByRequestId.getOrDefault(requestId, List.of())));
    }

    @Override
    public List<PlatformInteractionEventVO> interactionEvents(String sessionId) {
        return interactionEventsBySessionId.getOrDefault(sessionId, List.of()).stream()
                .sorted(Comparator.comparing(PlatformInteractionEventVO::occurredAt))
                .toList();
    }

    @Override
    public List<PlatformTimelineEventVO> sessionTimeline(String sessionId) {
        List<PlatformTimelineEventVO> timeline = new ArrayList<>();
        interactionEvents(sessionId).stream()
                .map(this::toTimelineEvent)
                .forEach(timeline::add);
        agentEventsBySessionId.getOrDefault(sessionId, List.of()).stream()
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
                event.toolCallId(),
                event.toolName(),
                event.agentName(),
                event.modelProvider(),
                event.modelName(),
                event.latencyMs(),
                event.data(),
                event.createdAt()
        );
        agentEventsByRequestId.computeIfAbsent(stored.requestId(), ignored -> new ArrayList<>()).add(stored);
        if (hasText(stored.sessionId())) {
            agentEventsBySessionId.computeIfAbsent(stored.sessionId(), ignored -> new ArrayList<>()).add(stored);
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
        interactionEventsBySessionId.computeIfAbsent(stored.sessionId(), ignored -> new ArrayList<>()).add(stored);
        return stored;
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
                        "data", event.data()
                )
        );
    }

    private String nullToEmpty(String value) {
        return value == null ? "" : value;
    }

    private boolean hasText(String value) {
        return value != null && !value.isBlank();
    }
}
