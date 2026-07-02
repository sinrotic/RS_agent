# Agent Run Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first version of `/observe` agent run monitoring so a developer can review one session/request with summary metrics, timeline events, event details, and light refresh.

**Architecture:** Keep the existing three-layer shape: `rs-service-agent` emits trace events, `rs-service-platform-trace` aggregates those events into a monitor view, and the React `/observe` page renders the view. The implementation is additive: no new service, no database migration, no WebSocket.

**Tech Stack:** Java 21 records, Spring Boot MVC, JUnit 5, AssertJ, MockMvc, React 18, TypeScript, Vite, Tailwind CSS, lucide-react.

---

## File Structure

Create or modify these files only:

- Create `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunEventVO.java`: frontend-facing normalized event record.
- Create `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunMonitorVO.java`: root monitor response.
- Create `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunPhaseVO.java`: phase summary.
- Create `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunRelatedTraceVO.java`: lightweight related trace links/counts.
- Create `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunSummaryVO.java`: top-level metric summary.
- Modify `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentTraceEventVO.java`: add optional normalized fields while preserving existing constructors.
- Modify `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/service/PlatformTraceService.java`: add monitor query methods.
- Modify `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/service/impl/InMemoryPlatformTraceService.java`: derive monitor view from stored events and related traces.
- Modify `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/controller/platform/PlatformAgentTraceController.java`: add request-level monitor endpoint.
- Modify `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/controller/platform/PlatformSessionTraceController.java`: add session-level monitor endpoint.
- Modify `java_agent/rs-service-platform-trace/src/test/java/com/sinrotic/rs/platformtrace/service/InMemoryPlatformTraceServiceTest.java`: cover aggregation and empty state.
- Modify `java_agent/rs-service-platform-trace/src/test/java/com/sinrotic/rs/platformtrace/controller/PlatformTraceControllerTest.java`: cover new endpoints.
- Modify `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentTraceEventVO.java`: keep outbound JSON aligned with platform trace.
- Modify `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java`: populate normalized trace fields.
- Modify `java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/service/InMemoryAgentOrchestrationServiceTest.java`: verify emitted trace data includes normalized fields.
- Modify `java_agent/frontend/src/types/platformTrace.ts`: add TypeScript monitor types.
- Modify `java_agent/frontend/src/api/platformTraceClient.ts`: add mock and real monitor client calls.
- Create `java_agent/frontend/src/utils/agentRunMonitor.ts`: pure helpers for labels, metric formatting, and auto-refresh stop decision.
- Create `java_agent/frontend/src/components/AgentRunMonitorPanel.tsx`: summary/overview/timeline/detail component.
- Modify `java_agent/frontend/src/views/ObserveConsole.tsx`: wire monitor query and panel into `/observe`.

Run commands from `D:\sinrotic_code\python_project\summer\RS_agent\java_agent` unless a task says otherwise.

### Task 1: Platform Trace Monitor Model and Service Tests

**Files:**
- Create: `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunEventVO.java`
- Create: `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunMonitorVO.java`
- Create: `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunPhaseVO.java`
- Create: `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunRelatedTraceVO.java`
- Create: `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunSummaryVO.java`
- Modify: `java_agent/rs-service-platform-trace/src/test/java/com/sinrotic/rs/platformtrace/service/InMemoryPlatformTraceServiceTest.java`

- [ ] **Step 1: Write failing service tests for monitor aggregation and empty monitor**

Append these tests to `InMemoryPlatformTraceServiceTest`:

```java
@Test
void requestMonitorAggregatesEventsPhasesSummaryAndQualitySignals() {
    InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();
    service.saveAgentTraceEvent(new AgentTraceEventVO(
            "evt_model_001",
            "sess_001",
            "agent_req_001",
            "model_response",
            "",
            "",
            "rs_agent",
            "spring_ai",
            "gpt-5",
            120L,
            100,
            30,
            130,
            2L,
            3L,
            "model_call",
            "success",
            "",
            "",
            "user asks for commuting headphones",
            "assistant selected 2 products",
            Map.of("final_answer_present", true),
            Instant.parse("2026-07-02T10:00:01Z")
    ));
    service.saveAgentTraceEvent(new AgentTraceEventVO(
            "evt_tool_001",
            "sess_001",
            "agent_req_001",
            "tool_result",
            "call_001",
            "recommend_semantic_recall",
            "rs_agent",
            "spring_ai",
            "gpt-5",
            80L,
            null,
            null,
            null,
            null,
            null,
            "recommend",
            "success",
            "",
            "",
            "query=commuting headphones",
            "items=2",
            Map.of("item_count", 2),
            Instant.parse("2026-07-02T10:00:02Z")
    ));

    AgentRunMonitorVO monitor = service.agentRequestMonitor("agent_req_001");

    assertThat(monitor.requestId()).isEqualTo("agent_req_001");
    assertThat(monitor.sessionId()).isEqualTo("sess_001");
    assertThat(monitor.status()).isEqualTo("success");
    assertThat(monitor.summary().totalLatencyMs()).isEqualTo(200L);
    assertThat(monitor.summary().totalTokens()).isEqualTo(130);
    assertThat(monitor.summary().toolCallCount()).isEqualTo(1);
    assertThat(monitor.summary().errorCount()).isZero();
    assertThat(monitor.summary().hasFinalAnswer()).isTrue();
    assertThat(monitor.phases()).extracting("phase").containsExactly("model_call", "recommend");
    assertThat(monitor.events()).extracting("eventId").containsExactly("evt_model_001", "evt_tool_001");
    assertThat(monitor.qualitySignals()).isEmpty();
}

@Test
void sessionMonitorReturnsPartialEmptyViewForMissingEvents() {
    InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();

    AgentRunMonitorVO monitor = service.agentSessionMonitor("missing_session", null);

    assertThat(monitor.sessionId()).isEqualTo("missing_session");
    assertThat(monitor.requestId()).isEqualTo("");
    assertThat(monitor.status()).isEqualTo("partial");
    assertThat(monitor.summary().totalLatencyMs()).isZero();
    assertThat(monitor.events()).isEmpty();
    assertThat(monitor.qualitySignals()).contains("partial_trace");
}
```

- [ ] **Step 2: Run the service tests and verify they fail**

Run:

```powershell
.\mvnw -pl rs-service-platform-trace -Dtest=InMemoryPlatformTraceServiceTest test
```

Expected: compilation fails because `AgentRunMonitorVO` and `agentRequestMonitor` / `agentSessionMonitor` do not exist.

- [ ] **Step 3: Add monitor VO records**

Create `AgentRunEventVO.java`:

```java
package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.Map;

public record AgentRunEventVO(
        @JsonProperty("event_id")
        String eventId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("event_type")
        String eventType,
        @JsonProperty("phase")
        String phase,
        @JsonProperty("status")
        String status,
        @JsonProperty("tool_call_id")
        String toolCallId,
        @JsonProperty("tool_name")
        String toolName,
        @JsonProperty("agent_name")
        String agentName,
        @JsonProperty("model_provider")
        String modelProvider,
        @JsonProperty("model_name")
        String modelName,
        @JsonProperty("latency_ms")
        Long latencyMs,
        @JsonProperty("prompt_tokens")
        Integer promptTokens,
        @JsonProperty("completion_tokens")
        Integer completionTokens,
        @JsonProperty("total_tokens")
        Integer totalTokens,
        @JsonProperty("error_code")
        String errorCode,
        @JsonProperty("error_message")
        String errorMessage,
        @JsonProperty("input_summary")
        String inputSummary,
        @JsonProperty("output_summary")
        String outputSummary,
        @JsonProperty("data")
        Map<String, Object> data,
        @JsonProperty("created_at")
        Instant createdAt
) {
    public AgentRunEventVO {
        eventId = valueOrEmpty(eventId);
        sessionId = valueOrEmpty(sessionId);
        requestId = valueOrEmpty(requestId);
        eventType = valueOrEmpty(eventType);
        phase = valueOrEmpty(phase);
        status = valueOrEmpty(status);
        toolCallId = valueOrEmpty(toolCallId);
        toolName = valueOrEmpty(toolName);
        agentName = valueOrEmpty(agentName);
        modelProvider = valueOrEmpty(modelProvider);
        modelName = valueOrEmpty(modelName);
        errorCode = valueOrEmpty(errorCode);
        errorMessage = valueOrEmpty(errorMessage);
        inputSummary = valueOrEmpty(inputSummary);
        outputSummary = valueOrEmpty(outputSummary);
        data = data == null ? Map.of() : Map.copyOf(data);
        createdAt = createdAt == null ? Instant.now() : createdAt;
    }

    private static String valueOrEmpty(String value) {
        return value == null ? "" : value;
    }
}
```

Create `AgentRunSummaryVO.java`:

```java
package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record AgentRunSummaryVO(
        @JsonProperty("total_latency_ms")
        long totalLatencyMs,
        @JsonProperty("prompt_tokens")
        int promptTokens,
        @JsonProperty("completion_tokens")
        int completionTokens,
        @JsonProperty("total_tokens")
        int totalTokens,
        @JsonProperty("model_provider")
        String modelProvider,
        @JsonProperty("model_name")
        String modelName,
        @JsonProperty("tool_call_count")
        int toolCallCount,
        @JsonProperty("error_count")
        int errorCount,
        @JsonProperty("recommend_item_count")
        int recommendItemCount,
        @JsonProperty("has_final_answer")
        boolean hasFinalAnswer
) {
    public AgentRunSummaryVO {
        modelProvider = modelProvider == null ? "" : modelProvider;
        modelName = modelName == null ? "" : modelName;
    }

    public static AgentRunSummaryVO empty() {
        return new AgentRunSummaryVO(0, 0, 0, 0, "", "", 0, 0, 0, false);
    }
}
```

Create `AgentRunPhaseVO.java`:

```java
package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record AgentRunPhaseVO(
        @JsonProperty("phase")
        String phase,
        @JsonProperty("status")
        String status,
        @JsonProperty("event_count")
        int eventCount,
        @JsonProperty("latency_ms")
        long latencyMs,
        @JsonProperty("total_tokens")
        int totalTokens
) {
    public AgentRunPhaseVO {
        phase = phase == null ? "" : phase;
        status = status == null ? "" : status;
    }
}
```

Create `AgentRunRelatedTraceVO.java`:

```java
package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record AgentRunRelatedTraceVO(
        @JsonProperty("agent_turn_count")
        int agentTurnCount,
        @JsonProperty("recommend_request_ids")
        List<String> recommendRequestIds,
        @JsonProperty("interaction_event_count")
        int interactionEventCount
) {
    public AgentRunRelatedTraceVO {
        recommendRequestIds = recommendRequestIds == null ? List.of() : List.copyOf(recommendRequestIds);
    }

    public static AgentRunRelatedTraceVO empty() {
        return new AgentRunRelatedTraceVO(0, List.of(), 0);
    }
}
```

Create `AgentRunMonitorVO.java`:

```java
package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record AgentRunMonitorVO(
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("status")
        String status,
        @JsonProperty("summary")
        AgentRunSummaryVO summary,
        @JsonProperty("phases")
        List<AgentRunPhaseVO> phases,
        @JsonProperty("events")
        List<AgentRunEventVO> events,
        @JsonProperty("quality_signals")
        List<String> qualitySignals,
        @JsonProperty("related_traces")
        AgentRunRelatedTraceVO relatedTraces
) {
    public AgentRunMonitorVO {
        sessionId = sessionId == null ? "" : sessionId;
        requestId = requestId == null ? "" : requestId;
        status = status == null ? "partial" : status;
        summary = summary == null ? AgentRunSummaryVO.empty() : summary;
        phases = phases == null ? List.of() : List.copyOf(phases);
        events = events == null ? List.of() : List.copyOf(events);
        qualitySignals = qualitySignals == null ? List.of() : List.copyOf(qualitySignals);
        relatedTraces = relatedTraces == null ? AgentRunRelatedTraceVO.empty() : relatedTraces;
    }

    public static AgentRunMonitorVO empty(String sessionId, String requestId) {
        return new AgentRunMonitorVO(
                sessionId,
                requestId,
                "partial",
                AgentRunSummaryVO.empty(),
                List.of(),
                List.of(),
                List.of("partial_trace"),
                AgentRunRelatedTraceVO.empty()
        );
    }
}
```

- [ ] **Step 4: Run the service tests and verify the expected remaining failure**

Run:

```powershell
.\mvnw -pl rs-service-platform-trace -Dtest=InMemoryPlatformTraceServiceTest test
```

Expected: compilation still fails because the service interface and `AgentTraceEventVO` normalized constructor do not exist.

- [ ] **Step 5: Leave task 1 uncommitted**

Do not commit after Task 1 because the new tests intentionally fail until Task 2 implements the service contract. Keep the working tree changes in place and continue directly to Task 2.

### Task 2: Platform Trace Monitor Aggregation

**Files:**
- Modify: `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentTraceEventVO.java`
- Modify: `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/service/PlatformTraceService.java`
- Modify: `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/service/impl/InMemoryPlatformTraceService.java`
- Test: `java_agent/rs-service-platform-trace/src/test/java/com/sinrotic/rs/platformtrace/service/InMemoryPlatformTraceServiceTest.java`

- [ ] **Step 1: Extend platform `AgentTraceEventVO` with normalized fields**

Replace `AgentTraceEventVO.java` with this record. It keeps the old constructors used by current tests and adds the new full constructor used by monitor tests.

```java
package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.Map;

public record AgentTraceEventVO(
        @JsonProperty("event_id")
        String eventId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("event_type")
        String eventType,
        @JsonProperty("tool_call_id")
        String toolCallId,
        @JsonProperty("tool_name")
        String toolName,
        @JsonProperty("agent_name")
        String agentName,
        @JsonProperty("model_provider")
        String modelProvider,
        @JsonProperty("model_name")
        String modelName,
        @JsonProperty("latency_ms")
        Long latencyMs,
        @JsonProperty("prompt_tokens")
        Integer promptTokens,
        @JsonProperty("completion_tokens")
        Integer completionTokens,
        @JsonProperty("total_tokens")
        Integer totalTokens,
        @JsonProperty("cache_read_input_tokens")
        Long cacheReadInputTokens,
        @JsonProperty("cache_write_input_tokens")
        Long cacheWriteInputTokens,
        @JsonProperty("phase")
        String phase,
        @JsonProperty("status")
        String status,
        @JsonProperty("error_code")
        String errorCode,
        @JsonProperty("error_message")
        String errorMessage,
        @JsonProperty("input_summary")
        String inputSummary,
        @JsonProperty("output_summary")
        String outputSummary,
        @JsonProperty("data")
        Map<String, Object> data,
        @JsonProperty("created_at")
        Instant createdAt
) {
    public AgentTraceEventVO(
            String eventId,
            String sessionId,
            String requestId,
            String eventType,
            String toolCallId,
            String toolName,
            String agentName,
            String modelProvider,
            String modelName,
            Long latencyMs,
            Integer promptTokens,
            Integer completionTokens,
            Integer totalTokens,
            Long cacheReadInputTokens,
            Long cacheWriteInputTokens,
            Map<String, Object> data,
            Instant createdAt
    ) {
        this(eventId, sessionId, requestId, eventType, toolCallId, toolName, agentName, modelProvider, modelName,
                latencyMs, promptTokens, completionTokens, totalTokens, cacheReadInputTokens, cacheWriteInputTokens,
                "", "", "", "", "", "", data, createdAt);
    }

    public AgentTraceEventVO(
            String eventId,
            String sessionId,
            String requestId,
            String eventType,
            String toolCallId,
            String toolName,
            String agentName,
            String modelProvider,
            String modelName,
            Long latencyMs,
            Map<String, Object> data,
            Instant createdAt
    ) {
        this(eventId, sessionId, requestId, eventType, toolCallId, toolName, agentName, modelProvider, modelName,
                latencyMs, null, null, null, null, null, data, createdAt);
    }

    public AgentTraceEventVO {
        eventId = eventId == null ? "" : eventId;
        sessionId = sessionId == null ? "" : sessionId;
        requestId = requestId == null ? "" : requestId;
        eventType = eventType == null ? "" : eventType;
        toolCallId = toolCallId == null ? "" : toolCallId;
        toolName = toolName == null ? "" : toolName;
        agentName = agentName == null ? "" : agentName;
        modelProvider = modelProvider == null ? "" : modelProvider;
        modelName = modelName == null ? "" : modelName;
        phase = phase == null ? "" : phase;
        status = status == null ? "" : status;
        errorCode = errorCode == null ? "" : errorCode;
        errorMessage = errorMessage == null ? "" : errorMessage;
        inputSummary = inputSummary == null ? "" : inputSummary;
        outputSummary = outputSummary == null ? "" : outputSummary;
        data = data == null ? Map.of() : Map.copyOf(data);
        createdAt = createdAt == null ? Instant.now() : createdAt;
    }
}
```

- [ ] **Step 2: Add monitor methods to `PlatformTraceService`**

Add import:

```java
import com.sinrotic.rs.platformtrace.domain.vo.AgentRunMonitorVO;
```

Add methods after `agentRequestEvents`:

```java
AgentRunMonitorVO agentRequestMonitor(String requestId);

AgentRunMonitorVO agentSessionMonitor(String sessionId, String requestId);
```

- [ ] **Step 3: Implement monitor aggregation**

In `InMemoryPlatformTraceService`, add import:

```java
import com.sinrotic.rs.platformtrace.domain.vo.AgentRunEventVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentRunMonitorVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentRunPhaseVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentRunRelatedTraceVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentRunSummaryVO;
import java.util.LinkedHashMap;
```

In `saveAgentTraceEvent`, update the stored constructor to preserve normalized fields:

```java
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
        event.promptTokens(),
        event.completionTokens(),
        event.totalTokens(),
        event.cacheReadInputTokens(),
        event.cacheWriteInputTokens(),
        event.phase(),
        event.status(),
        event.errorCode(),
        event.errorMessage(),
        event.inputSummary(),
        event.outputSummary(),
        event.data(),
        event.createdAt()
);
```

Add these methods before `saveAccountProfile`:

```java
@Override
public AgentRunMonitorVO agentRequestMonitor(String requestId) {
    if (!hasText(requestId)) {
        return AgentRunMonitorVO.empty("", "");
    }
    List<AgentTraceEventVO> events = agentEventsByRequestId.getOrDefault(requestId, List.of()).stream()
            .sorted(Comparator.comparing(AgentTraceEventVO::createdAt))
            .toList();
    String sessionId = events.stream()
            .map(AgentTraceEventVO::sessionId)
            .filter(this::hasText)
            .findFirst()
            .orElse("");
    return buildMonitor(sessionId, requestId, events);
}

@Override
public AgentRunMonitorVO agentSessionMonitor(String sessionId, String requestId) {
    if (!hasText(sessionId)) {
        return AgentRunMonitorVO.empty("", requestId);
    }
    List<AgentTraceEventVO> events = agentEventsBySessionId.getOrDefault(sessionId, List.of()).stream()
            .filter(event -> !hasText(requestId) || requestId.equals(event.requestId()))
            .sorted(Comparator.comparing(AgentTraceEventVO::createdAt))
            .toList();
    String resolvedRequestId = hasText(requestId)
            ? requestId
            : events.stream().map(AgentTraceEventVO::requestId).filter(this::hasText).reduce((first, second) -> second).orElse("");
    return buildMonitor(sessionId, resolvedRequestId, events);
}

private AgentRunMonitorVO buildMonitor(String sessionId, String requestId, List<AgentTraceEventVO> sourceEvents) {
    if (sourceEvents == null || sourceEvents.isEmpty()) {
        return AgentRunMonitorVO.empty(sessionId, requestId);
    }
    List<AgentRunEventVO> events = sourceEvents.stream().map(this::toRunEvent).toList();
    AgentRunSummaryVO summary = buildSummary(sessionId, events);
    List<AgentRunPhaseVO> phases = buildPhases(events);
    List<String> qualitySignals = buildQualitySignals(events, summary);
    return new AgentRunMonitorVO(
            sessionId,
            requestId,
            resolveRunStatus(events, qualitySignals),
            summary,
            phases,
            events,
            qualitySignals,
            buildRelatedTrace(sessionId)
    );
}

private AgentRunEventVO toRunEvent(AgentTraceEventVO event) {
    return new AgentRunEventVO(
            event.eventId(),
            event.sessionId(),
            event.requestId(),
            event.eventType(),
            hasText(event.phase()) ? event.phase() : inferPhase(event),
            hasText(event.status()) ? event.status() : inferStatus(event),
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

private AgentRunSummaryVO buildSummary(String sessionId, List<AgentRunEventVO> events) {
    long latency = events.stream().map(AgentRunEventVO::latencyMs).filter(java.util.Objects::nonNull).mapToLong(Long::longValue).sum();
    int promptTokens = events.stream().map(AgentRunEventVO::promptTokens).filter(java.util.Objects::nonNull).mapToInt(Integer::intValue).sum();
    int completionTokens = events.stream().map(AgentRunEventVO::completionTokens).filter(java.util.Objects::nonNull).mapToInt(Integer::intValue).sum();
    int totalTokens = events.stream().map(AgentRunEventVO::totalTokens).filter(java.util.Objects::nonNull).mapToInt(Integer::intValue).sum();
    int toolCallCount = (int) events.stream().filter(event -> hasText(event.toolName())).count();
    int errorCount = (int) events.stream().filter(event -> "error".equalsIgnoreCase(event.status())).count();
    String modelProvider = events.stream().map(AgentRunEventVO::modelProvider).filter(this::hasText).findFirst().orElse("");
    String modelName = events.stream().map(AgentRunEventVO::modelName).filter(this::hasText).findFirst().orElse("");
    int recommendItemCount = recommendTraces.values().stream()
            .filter(trace -> sessionId.equals(trace.sessionId()))
            .mapToInt(trace -> trace.items().size())
            .sum();
    boolean hasFinalAnswer = events.stream().anyMatch(this::hasFinalAnswerSignal);
    return new AgentRunSummaryVO(latency, promptTokens, completionTokens, totalTokens, modelProvider, modelName,
            toolCallCount, errorCount, recommendItemCount, hasFinalAnswer);
}

private List<AgentRunPhaseVO> buildPhases(List<AgentRunEventVO> events) {
    Map<String, List<AgentRunEventVO>> byPhase = new LinkedHashMap<>();
    for (AgentRunEventVO event : events) {
        byPhase.computeIfAbsent(hasText(event.phase()) ? event.phase() : "unknown", ignored -> new ArrayList<>()).add(event);
    }
    List<AgentRunPhaseVO> phases = new ArrayList<>();
    for (Map.Entry<String, List<AgentRunEventVO>> entry : byPhase.entrySet()) {
        List<AgentRunEventVO> phaseEvents = entry.getValue();
        long latency = phaseEvents.stream().map(AgentRunEventVO::latencyMs).filter(java.util.Objects::nonNull).mapToLong(Long::longValue).sum();
        int tokens = phaseEvents.stream().map(AgentRunEventVO::totalTokens).filter(java.util.Objects::nonNull).mapToInt(Integer::intValue).sum();
        String status = phaseEvents.stream().anyMatch(event -> "error".equalsIgnoreCase(event.status())) ? "failed" : "success";
        phases.add(new AgentRunPhaseVO(entry.getKey(), status, phaseEvents.size(), latency, tokens));
    }
    return List.copyOf(phases);
}

private List<String> buildQualitySignals(List<AgentRunEventVO> events, AgentRunSummaryVO summary) {
    List<String> signals = new ArrayList<>();
    if (!summary.hasFinalAnswer()) {
        signals.add("missing_final_answer");
    }
    if (summary.errorCount() > 0) {
        boolean toolError = events.stream().anyMatch(event -> hasText(event.toolName()) && "error".equalsIgnoreCase(event.status()));
        signals.add(toolError ? "tool_error" : "model_error");
    }
    if (summary.totalLatencyMs() > 10_000L) {
        signals.add("high_latency");
    }
    if (summary.recommendItemCount() == 0 && events.stream().anyMatch(event -> "recommend".equals(event.phase()))) {
        signals.add("no_recommendation_items");
    }
    return List.copyOf(signals);
}

private AgentRunRelatedTraceVO buildRelatedTrace(String sessionId) {
    if (!hasText(sessionId)) {
        return AgentRunRelatedTraceVO.empty();
    }
    List<String> recommendRequestIds = recommendTraces.values().stream()
            .filter(trace -> sessionId.equals(trace.sessionId()))
            .map(RecommendTraceVO::requestId)
            .sorted()
            .toList();
    return new AgentRunRelatedTraceVO(
            agentSessionTurns(sessionId).turns().size(),
            recommendRequestIds,
            interactionEvents(sessionId).size()
    );
}

private String resolveRunStatus(List<AgentRunEventVO> events, List<String> qualitySignals) {
    if (events.stream().anyMatch(event -> "error".equalsIgnoreCase(event.status()))) {
        return "failed";
    }
    if (qualitySignals.contains("partial_trace")) {
        return "partial";
    }
    boolean terminal = events.stream().anyMatch(event ->
            "agent_done".equals(event.eventType()) || "final_answer".equals(event.phase()) || hasFinalAnswerSignal(event));
    return terminal ? "success" : "running";
}

private String inferPhase(AgentTraceEventVO event) {
    if (hasText(event.toolName())) {
        if (event.toolName().contains("rag")) {
            return "rag";
        }
        if (event.toolName().contains("recommend")) {
            return "recommend";
        }
        return "tool_call";
    }
    if (event.eventType().contains("final") || event.eventType().contains("done")) {
        return "final_answer";
    }
    if (event.eventType().contains("model")) {
        return "model_call";
    }
    return "agent";
}

private String inferStatus(AgentTraceEventVO event) {
    Object status = event.data().get("status");
    if (status != null && "ERROR".equalsIgnoreCase(String.valueOf(status))) {
        return "error";
    }
    if (hasText(event.errorCode()) || hasText(event.errorMessage()) || event.eventType().contains("error")) {
        return "error";
    }
    return "success";
}

private boolean hasFinalAnswerSignal(AgentRunEventVO event) {
    return "final_answer".equals(event.phase())
            || "agent_done".equals(event.eventType())
            || Boolean.TRUE.equals(event.data().get("final_answer_present"));
}
```

- [ ] **Step 4: Run platform trace service tests**

Run:

```powershell
.\mvnw -pl rs-service-platform-trace -Dtest=InMemoryPlatformTraceServiceTest test
```

Expected: all tests in `InMemoryPlatformTraceServiceTest` pass.

- [ ] **Step 5: Commit task 2**

```powershell
git add rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunEventVO.java `
        rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunMonitorVO.java `
        rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunPhaseVO.java `
        rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunRelatedTraceVO.java `
        rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentRunSummaryVO.java `
        rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/domain/vo/AgentTraceEventVO.java `
        rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/service/PlatformTraceService.java `
        rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/service/impl/InMemoryPlatformTraceService.java `
        rs-service-platform-trace/src/test/java/com/sinrotic/rs/platformtrace/service/InMemoryPlatformTraceServiceTest.java
git commit -m "feat: aggregate agent run monitor"
```

### Task 3: Platform Trace Monitor API

**Files:**
- Modify: `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/controller/platform/PlatformAgentTraceController.java`
- Modify: `java_agent/rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/controller/platform/PlatformSessionTraceController.java`
- Modify: `java_agent/rs-service-platform-trace/src/test/java/com/sinrotic/rs/platformtrace/controller/PlatformTraceControllerTest.java`

- [ ] **Step 1: Write failing MockMvc tests**

In `PlatformTraceControllerTest`, import `AgentTraceEventVO` and `Instant`:

```java
import com.sinrotic.rs.platformtrace.domain.vo.AgentTraceEventVO;
import java.time.Instant;
```

In `setUp`, after `saveAgentSessionTrace`, add:

```java
traceService.saveAgentTraceEvent(new AgentTraceEventVO(
        "evt_model_001",
        "sess_001",
        "agent_req_001",
        "model_response",
        "",
        "",
        "rs_agent",
        "spring_ai",
        "gpt-5",
        120L,
        100,
        30,
        130,
        0L,
        0L,
        "model_call",
        "success",
        "",
        "",
        "user asks for backpack",
        "assistant selected B001",
        Map.of("final_answer_present", true),
        Instant.parse("2026-07-02T10:00:01Z")
));
```

Append tests:

```java
@Test
void requestMonitorEndpointReturnsAgentRunMonitor() throws Exception {
    mockMvc.perform(get("/api/platform/agent/runs/agent_req_001/monitor"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.request_id").value("agent_req_001"))
            .andExpect(jsonPath("$.session_id").value("sess_001"))
            .andExpect(jsonPath("$.status").value("success"))
            .andExpect(jsonPath("$.summary.total_tokens").value(130))
            .andExpect(jsonPath("$.events[0].phase").value("model_call"));
}

@Test
void sessionMonitorEndpointReturnsAgentRunMonitor() throws Exception {
    mockMvc.perform(get("/api/platform/sessions/sess_001/agent-monitor")
                    .param("request_id", "agent_req_001"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.session_id").value("sess_001"))
            .andExpect(jsonPath("$.request_id").value("agent_req_001"))
            .andExpect(jsonPath("$.summary.has_final_answer").value(true));
}
```

- [ ] **Step 2: Run controller tests and verify they fail**

Run:

```powershell
.\mvnw -pl rs-service-platform-trace -Dtest=PlatformTraceControllerTest test
```

Expected: 404 for the two new endpoints.

- [ ] **Step 3: Add controller endpoints**

In `PlatformAgentTraceController`, import:

```java
import com.sinrotic.rs.platformtrace.domain.vo.AgentRunMonitorVO;
```

Add:

```java
@GetMapping("/runs/{requestId}/monitor")
public AgentRunMonitorVO agentRequestMonitor(@PathVariable String requestId) {
    return traceService.agentRequestMonitor(requestId);
}
```

In `PlatformSessionTraceController`, import:

```java
import com.sinrotic.rs.platformtrace.domain.vo.AgentRunMonitorVO;
```

Add:

```java
@GetMapping("/{sessionId}/agent-monitor")
public AgentRunMonitorVO agentSessionMonitor(
        @PathVariable String sessionId,
        @RequestParam(name = "request_id", required = false) String requestId
) {
    return traceService.agentSessionMonitor(sessionId, requestId);
}
```

- [ ] **Step 4: Run controller tests**

Run:

```powershell
.\mvnw -pl rs-service-platform-trace -Dtest=PlatformTraceControllerTest test
```

Expected: all tests pass.

- [ ] **Step 5: Commit task 3**

```powershell
git add rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/controller/platform/PlatformAgentTraceController.java `
        rs-service-platform-trace/src/main/java/com/sinrotic/rs/platformtrace/controller/platform/PlatformSessionTraceController.java `
        rs-service-platform-trace/src/test/java/com/sinrotic/rs/platformtrace/controller/PlatformTraceControllerTest.java
git commit -m "feat: expose agent run monitor endpoints"
```

### Task 4: Agent Trace Event Normalization

**Files:**
- Modify: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentTraceEventVO.java`
- Modify: `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java`
- Modify: `java_agent/rs-service-agent/src/test/java/com/sinrotic/rs/agent/service/InMemoryAgentOrchestrationServiceTest.java`

- [ ] **Step 1: Write failing agent trace test**

In `InMemoryAgentOrchestrationServiceTest`, modify the existing `streamChatReportsAgentEventsWithStableToolCallIds` test. Replace the final `anySatisfy` assertion with this block:

```java
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
```

- [ ] **Step 2: Run the agent orchestration test and verify failure**

Run:

```powershell
.\mvnw -pl rs-service-agent -Dtest=InMemoryAgentOrchestrationServiceTest test
```

Expected: compilation fails because agent `AgentTraceEventVO` has no normalized accessors.

- [ ] **Step 3: Align agent `AgentTraceEventVO` with platform trace**

Replace `rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentTraceEventVO.java` with the same record shape used in Task 2. Keep the package line as:

```java
package com.sinrotic.rs.agent.domain.vo;
```

All fields, constructors, and JSON property names should match the platform trace version exactly.

- [ ] **Step 4: Populate normalized fields in `reportTraceEvent`**

In `InMemoryAgentOrchestrationService.reportTraceEvent`, replace the `new AgentTraceEventVO(...)` call with:

```java
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
        longValue(data.get("latency_ms")),
        integerValue(data.get("prompt_tokens")),
        integerValue(data.get("completion_tokens")),
        integerValue(data.get("total_tokens")),
        longValue(data.get("cache_read_input_tokens")),
        longValue(data.get("cache_write_input_tokens")),
        inferTracePhase(eventType, toolName),
        inferTraceStatus(eventType, data),
        stringValue(data.get("error_code")),
        stringValue(data.get("error_message")),
        summarizeTraceInput(data),
        summarizeTraceOutput(data),
        data,
        java.time.Instant.now()
));
```

Add helper methods near `stringValue`:

```java
private String inferTracePhase(String eventType, String toolName) {
    if (toolName != null && !toolName.isBlank()) {
        if (toolName.contains("rag")) {
            return "rag";
        }
        if (toolName.contains("recommend")) {
            return "recommend";
        }
        return "tool_call";
    }
    if (eventType != null && (eventType.contains("done") || eventType.contains("final"))) {
        return "final_answer";
    }
    if (eventType != null && eventType.contains("model")) {
        return "model_call";
    }
    return "agent";
}

private String inferTraceStatus(String eventType, Map<String, Object> data) {
    Object status = data.get("status");
    if (status != null && "ERROR".equalsIgnoreCase(String.valueOf(status))) {
        return "error";
    }
    if (data.containsKey("error_code") || data.containsKey("error_message")) {
        return "error";
    }
    if (eventType != null && eventType.contains("error")) {
        return "error";
    }
    return "success";
}

private String summarizeTraceInput(Map<String, Object> data) {
    Object query = data.get("query");
    if (query != null) {
        return "query=" + query;
    }
    Object toolArguments = data.get("tool_arguments");
    if (toolArguments != null) {
        return truncateSummary(String.valueOf(toolArguments));
    }
    return "";
}

private String summarizeTraceOutput(Map<String, Object> data) {
    Object outputSummary = data.get("output_summary");
    if (outputSummary != null) {
        return truncateSummary(String.valueOf(outputSummary));
    }
    Object status = data.get("status");
    if (status != null) {
        return "status=" + status;
    }
    return "";
}

private String truncateSummary(String value) {
    if (value == null) {
        return "";
    }
    return value.length() <= 240 ? value : value.substring(0, 240);
}
```

- [ ] **Step 5: Run agent test**

Run:

```powershell
.\mvnw -pl rs-service-agent -Dtest=InMemoryAgentOrchestrationServiceTest test
```

Expected: the test passes.

- [ ] **Step 6: Commit task 4**

```powershell
git add rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentTraceEventVO.java `
        rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java `
        rs-service-agent/src/test/java/com/sinrotic/rs/agent/service/InMemoryAgentOrchestrationServiceTest.java
git commit -m "feat: normalize agent trace events"
```

### Task 5: Frontend Monitor Types, Client, and Helpers

**Files:**
- Modify: `java_agent/frontend/src/types/platformTrace.ts`
- Modify: `java_agent/frontend/src/api/platformTraceClient.ts`
- Create: `java_agent/frontend/src/utils/agentRunMonitor.ts`

- [ ] **Step 1: Add TypeScript monitor types**

Append to `platformTrace.ts`:

```ts
export type AgentRunStatus = 'running' | 'success' | 'failed' | 'partial';

export interface AgentRunSummaryVO {
  total_latency_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  model_provider: string;
  model_name: string;
  tool_call_count: number;
  error_count: number;
  recommend_item_count: number;
  has_final_answer: boolean;
}

export interface AgentRunPhaseVO {
  phase: string;
  status: string;
  event_count: number;
  latency_ms: number;
  total_tokens: number;
}

export interface AgentRunEventVO {
  event_id: string;
  session_id: string;
  request_id: string;
  event_type: string;
  phase: string;
  status: string;
  tool_call_id: string;
  tool_name: string;
  agent_name: string;
  model_provider: string;
  model_name: string;
  latency_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  error_code: string;
  error_message: string;
  input_summary: string;
  output_summary: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface AgentRunRelatedTraceVO {
  agent_turn_count: number;
  recommend_request_ids: string[];
  interaction_event_count: number;
}

export interface AgentRunMonitorVO {
  session_id: string;
  request_id: string;
  status: AgentRunStatus;
  summary: AgentRunSummaryVO;
  phases: AgentRunPhaseVO[];
  events: AgentRunEventVO[];
  quality_signals: string[];
  related_traces: AgentRunRelatedTraceVO;
}
```

- [ ] **Step 2: Add monitor API client with mock response**

Update the import in `platformTraceClient.ts`:

```ts
import {
  AgentRunMonitorVO,
  PlatformSessionOverviewVO,
  PlatformTimelineEventVO,
  RecommendTraceVO
} from '../types/platformTrace';
```

Add this function after `mockRecommendTrace`:

```ts
function mockAgentRunMonitor(sessionId: string, requestId: string): AgentRunMonitorVO {
  const resolvedSessionId = sessionId || 'mock-session';
  const resolvedRequestId = requestId || 'agent_req_mock_001';
  const createdAt = new Date(Date.now() - 120000).toISOString();
  return {
    session_id: resolvedSessionId,
    request_id: resolvedRequestId,
    status: 'success',
    summary: {
      total_latency_ms: 384,
      prompt_tokens: 420,
      completion_tokens: 120,
      total_tokens: 540,
      model_provider: 'mock',
      model_name: 'gpt-5-mock',
      tool_call_count: 2,
      error_count: 0,
      recommend_item_count: 4,
      has_final_answer: true
    },
    phases: [
      { phase: 'model_call', status: 'success', event_count: 1, latency_ms: 180, total_tokens: 540 },
      { phase: 'recommend', status: 'success', event_count: 1, latency_ms: 120, total_tokens: 0 },
      { phase: 'final_answer', status: 'success', event_count: 1, latency_ms: 84, total_tokens: 0 }
    ],
    events: [
      {
        event_id: 'agent_evt_mock_model',
        session_id: resolvedSessionId,
        request_id: resolvedRequestId,
        event_type: 'model_response',
        phase: 'model_call',
        status: 'success',
        tool_call_id: '',
        tool_name: '',
        agent_name: 'rs_agent',
        model_provider: 'mock',
        model_name: 'gpt-5-mock',
        latency_ms: 180,
        prompt_tokens: 420,
        completion_tokens: 120,
        total_tokens: 540,
        error_code: '',
        error_message: '',
        input_summary: 'Need a commuting product recommendation',
        output_summary: 'Selected audio and portable candidates',
        data: { final_answer_present: true },
        created_at: createdAt
      }
    ],
    quality_signals: [],
    related_traces: {
      agent_turn_count: 1,
      recommend_request_ids: [requestId || 'mock-rec-req'],
      interaction_event_count: 2
    }
  };
}
```

Add exported client calls:

```ts
export async function getAgentRequestMonitor(requestId: string): Promise<AgentRunMonitorVO> {
  if (isMockMode()) {
    await mockDelay(250);
    return mockAgentRunMonitor('mock-session', requestId);
  }
  return getJson<AgentRunMonitorVO>(`/platform/agent/runs/${encodeURIComponent(requestId)}/monitor`);
}

export async function getAgentSessionMonitor(sessionId: string, requestId?: string): Promise<AgentRunMonitorVO> {
  if (isMockMode()) {
    await mockDelay(250);
    return mockAgentRunMonitor(sessionId, requestId || 'agent_req_mock_001');
  }
  const params = new URLSearchParams();
  if (requestId) params.set('request_id', requestId);
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return getJson<AgentRunMonitorVO>(`/platform/sessions/${encodeURIComponent(sessionId)}/agent-monitor${suffix}`);
}
```

- [ ] **Step 3: Add pure helper utilities**

Create `agentRunMonitor.ts`:

```ts
import { AgentRunEventVO, AgentRunMonitorVO, AgentRunStatus } from '../types/platformTrace';

export function formatMs(value?: number): string {
  if (!value || value <= 0) return '-';
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

export function formatTokens(value?: number): string {
  if (!value || value <= 0) return '-';
  return value.toLocaleString();
}

export function statusTone(status: AgentRunStatus | string): string {
  if (status === 'success') return 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10';
  if (status === 'failed' || status === 'error') return 'text-rose-300 border-rose-500/30 bg-rose-500/10';
  if (status === 'running') return 'text-cyan-300 border-cyan-500/30 bg-cyan-500/10';
  return 'text-amber-300 border-amber-500/30 bg-amber-500/10';
}

export function shouldAutoRefresh(monitor: AgentRunMonitorVO | null): boolean {
  return monitor?.status === 'running' || monitor?.status === 'partial';
}

export function eventTitle(event: AgentRunEventVO): string {
  return event.tool_name || event.event_type || event.phase || event.event_id;
}

export function sortRunEvents(events: AgentRunEventVO[]): AgentRunEventVO[] {
  return [...events].sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at));
}
```

- [ ] **Step 4: Run frontend typecheck**

Run from `java_agent/frontend`:

```powershell
npm run lint
```

Expected: TypeScript passes.

- [ ] **Step 5: Commit task 5**

```powershell
git add frontend/src/types/platformTrace.ts `
        frontend/src/api/platformTraceClient.ts `
        frontend/src/utils/agentRunMonitor.ts
git commit -m "feat: add frontend agent run monitor client"
```

### Task 6: Frontend Monitor Panel and Observe Wiring

**Files:**
- Create: `java_agent/frontend/src/components/AgentRunMonitorPanel.tsx`
- Modify: `java_agent/frontend/src/views/ObserveConsole.tsx`

- [ ] **Step 1: Create monitor panel component**

Create `AgentRunMonitorPanel.tsx`:

```tsx
import { ReactNode, useMemo, useState } from 'react';
import { AlertTriangle, FileJson, RefreshCw, Route, Timer } from 'lucide-react';
import { AgentRunEventVO, AgentRunMonitorVO } from '../types/platformTrace';
import { eventTitle, formatMs, formatTokens, sortRunEvents, statusTone } from '../utils/agentRunMonitor';

interface AgentRunMonitorPanelProps {
  monitor: AgentRunMonitorVO | null;
  loading: boolean;
  autoRefresh: boolean;
  onRefresh: () => void;
  onAutoRefreshChange: (enabled: boolean) => void;
}

export function AgentRunMonitorPanel({
  monitor,
  loading,
  autoRefresh,
  onRefresh,
  onAutoRefreshChange
}: AgentRunMonitorPanelProps) {
  const events = useMemo(() => sortRunEvents(monitor?.events || []), [monitor]);
  const [selectedEventId, setSelectedEventId] = useState<string>('');
  const selectedEvent = events.find((event) => event.event_id === selectedEventId) || events[0] || null;

  if (!monitor) {
    return (
      <section className="rounded-lg border border-slate-800 bg-slate-900/70 p-6 text-xs text-slate-500">
        输入 sessionId 或 requestId 后查看 Agent 运行摘要、时间线和事件详情。
      </section>
    );
  }

  return (
    <section className="space-y-4">
      <div className="grid grid-cols-2 gap-3 text-xs lg:grid-cols-7">
        <Metric label="Status" value={monitor.status} tone={statusTone(monitor.status)} />
        <Metric label="Latency" value={formatMs(monitor.summary.total_latency_ms)} />
        <Metric label="Tokens" value={formatTokens(monitor.summary.total_tokens)} />
        <Metric label="Model" value={monitor.summary.model_name || monitor.summary.model_provider || '-'} />
        <Metric label="Tools" value={String(monitor.summary.tool_call_count)} />
        <Metric label="Errors" value={String(monitor.summary.error_count)} tone={monitor.summary.error_count > 0 ? statusTone('error') : undefined} />
        <Metric label="Final" value={monitor.summary.has_final_answer ? 'Yes' : 'No'} />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900/70 px-4 py-3">
        <div className="min-w-0 text-xs text-slate-400">
          <div className="font-mono text-[10px] text-slate-500">session: {monitor.session_id || '-'}</div>
          <div className="mt-1 font-mono text-[10px] text-slate-500">request: {monitor.request_id || '-'}</div>
        </div>
        <div className="flex items-center gap-2">
          <label className="inline-flex items-center gap-2 text-[11px] font-bold text-slate-300">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(event) => onAutoRefreshChange(event.target.checked)}
            />
            自动刷新
          </label>
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-[11px] font-bold text-slate-200 hover:border-cyan-500 disabled:opacity-50"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            刷新
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[260px_1fr_360px]">
        <aside className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/70 p-4">
          <SectionTitle icon={<Route size={14} />} title="运行概览" />
          <div className="space-y-2 text-xs text-slate-400">
            {monitor.phases.map((phase) => (
              <div key={phase.phase} className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-bold text-slate-200">{phase.phase}</span>
                  <span className={`rounded border px-2 py-0.5 text-[10px] ${statusTone(phase.status)}`}>{phase.status}</span>
                </div>
                <div className="mt-2 flex justify-between text-[11px]">
                  <span>{phase.event_count} events</span>
                  <span>{formatMs(phase.latency_ms)}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="border-t border-slate-800 pt-3">
            <div className="mb-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">质量信号</div>
            {monitor.quality_signals.length === 0 ? (
              <div className="text-xs text-slate-500">暂无异常信号</div>
            ) : (
              <div className="flex flex-wrap gap-1">
                {monitor.quality_signals.map((signal) => (
                  <span key={signal} className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] font-bold text-amber-300">
                    {signal}
                  </span>
                ))}
              </div>
            )}
          </div>
        </aside>

        <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/70">
          <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3 text-xs font-bold text-slate-100">
            <Timer size={14} className="text-cyan-300" />
            运行时间线
          </div>
          {events.length === 0 ? (
            <div className="px-4 py-10 text-center text-xs text-slate-500">暂无 Agent 运行事件。</div>
          ) : (
            <div className="divide-y divide-slate-800">
              {events.map((event) => (
                <button
                  key={event.event_id}
                  type="button"
                  onClick={() => setSelectedEventId(event.event_id)}
                  className={`grid w-full grid-cols-[92px_110px_1fr_90px_90px] gap-3 px-4 py-3 text-left text-xs transition hover:bg-slate-800/60 ${
                    selectedEvent?.event_id === event.event_id ? 'bg-cyan-500/10' : ''
                  }`}
                >
                  <span className="font-mono text-[10px] text-slate-500">{new Date(event.created_at).toLocaleTimeString()}</span>
                  <span className={`w-fit rounded border px-2 py-0.5 text-[10px] font-bold ${statusTone(event.status)}`}>{event.status}</span>
                  <span className="min-w-0">
                    <span className="block truncate font-bold text-slate-200">{eventTitle(event)}</span>
                    <span className="mt-1 block truncate text-[10px] text-slate-500">{event.phase}</span>
                  </span>
                  <span className="text-slate-400">{formatMs(event.latency_ms)}</span>
                  <span className="text-slate-400">{formatTokens(event.total_tokens)}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <EventDetail event={selectedEvent} />
      </div>
    </section>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className={`rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2 ${tone || ''}`}>
      <div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-extrabold text-slate-100">{value}</div>
    </div>
  );
}

function SectionTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2 text-xs font-bold text-slate-100">
      {icon}
      {title}
    </div>
  );
}

function EventDetail({ event }: { event: AgentRunEventVO | null }) {
  if (!event) {
    return (
      <aside className="rounded-lg border border-slate-800 bg-slate-900/70 p-4 text-xs text-slate-500">
        选择时间线事件查看详情。
      </aside>
    );
  }
  return (
    <aside className="space-y-4 rounded-lg border border-slate-800 bg-slate-900/70 p-4">
      <SectionTitle icon={<FileJson size={14} />} title="事件详情" />
      <Detail label="Event" value={event.event_id} />
      <Detail label="Type" value={event.event_type} />
      <Detail label="Tool" value={event.tool_name || '-'} />
      <Detail label="Input" value={event.input_summary || '-'} />
      <Detail label="Output" value={event.output_summary || '-'} />
      {(event.error_code || event.error_message) && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
          <div className="flex items-center gap-2 font-bold">
            <AlertTriangle size={13} />
            {event.error_code || 'error'}
          </div>
          <div className="mt-1 whitespace-pre-wrap">{event.error_message}</div>
        </div>
      )}
      <pre className="max-h-[280px] overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-3 text-[10px] text-slate-300">
        {JSON.stringify(event.data, null, 2)}
      </pre>
    </aside>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-xs">
      <div className="mb-1 text-[10px] font-bold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="break-words rounded-lg border border-slate-800 bg-slate-950/60 p-2 text-slate-300">{value}</div>
    </div>
  );
}
```

- [ ] **Step 2: Wire monitor state into `ObserveConsole`**

Update imports in `ObserveConsole.tsx`:

```tsx
import { FormEvent, useEffect, useState } from 'react';
import { Activity, Database, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import {
  getAgentRequestMonitor,
  getAgentSessionMonitor,
  getRecommendTrace,
  getSessionOverview
} from '../api/platformTraceClient';
import { AgentRunMonitorVO, PlatformSessionOverviewVO, RecommendTraceVO } from '../types/platformTrace';
import { shouldAutoRefresh } from '../utils/agentRunMonitor';
import { AgentRunMonitorPanel } from '../components/AgentRunMonitorPanel';
```

Add state after `recommendTrace`:

```tsx
const [monitor, setMonitor] = useState<AgentRunMonitorVO | null>(null);
const [autoRefresh, setAutoRefresh] = useState<boolean>(false);
```

Add loader:

```tsx
const loadMonitor = async () => {
  const trimmedSessionId = sessionId.trim();
  const trimmedRequestId = requestId.trim();
  if (!trimmedSessionId && !trimmedRequestId) return;
  const data = trimmedSessionId
    ? await getAgentSessionMonitor(trimmedSessionId, trimmedRequestId || undefined)
    : await getAgentRequestMonitor(trimmedRequestId);
  setMonitor(data);
  if (!sessionId && data.session_id) {
    setSessionId(data.session_id);
  }
};
```

In `loadOverview`, after `setOverview(data);`, add:

```tsx
await loadMonitor();
```

In `loadRecommendTrace`, after possible `setSessionId`, add:

```tsx
await loadMonitor();
```

Add effect before `return`:

```tsx
useEffect(() => {
  if (!autoRefresh || !shouldAutoRefresh(monitor)) return;
  const id = window.setInterval(() => {
    loadMonitor().catch((e: any) => setError(e.message || 'Failed to refresh agent monitor'));
  }, 5000);
  return () => window.clearInterval(id);
}, [autoRefresh, monitor?.status, sessionId, requestId]);
```

Replace the current five-card metrics in the header with monitor-aware values:

```tsx
<div className="grid grid-cols-2 gap-3 text-[10px] font-bold uppercase tracking-wide text-slate-400 sm:grid-cols-5">
  <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
    Status
    <div className="mt-1 text-sm text-cyan-300">{monitor?.status || 'Idle'}</div>
  </div>
  <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
    Tokens
    <div className="mt-1 text-sm text-cyan-300">{monitor?.summary.total_tokens || totalSessionTokens}</div>
  </div>
  <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
    Tools
    <div className="mt-1 text-sm text-cyan-300">{monitor?.summary.tool_call_count || 0}</div>
  </div>
  <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
    Errors
    <div className="mt-1 text-sm text-cyan-300">{monitor?.summary.error_count || 0}</div>
  </div>
  <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
    Recommend
    <div className="mt-1 text-sm text-cyan-300">{recommendTrace?.items.length || monitor?.summary.recommend_item_count || 0}</div>
  </div>
</div>
```

Insert `AgentRunMonitorPanel` above the existing two-column trace/recommend content:

```tsx
<AgentRunMonitorPanel
  monitor={monitor}
  loading={loading}
  autoRefresh={autoRefresh}
  onRefresh={() => {
    setLoading(true);
    setError('');
    loadMonitor()
      .catch((e: any) => setError(e.message || 'Failed to load agent monitor'))
      .finally(() => setLoading(false));
  }}
  onAutoRefreshChange={setAutoRefresh}
/>
```

- [ ] **Step 3: Run frontend typecheck**

Run from `java_agent/frontend`:

```powershell
npm run lint
```

Expected: TypeScript passes.

- [ ] **Step 4: Commit task 6**

```powershell
git add frontend/src/components/AgentRunMonitorPanel.tsx frontend/src/views/ObserveConsole.tsx
git commit -m "feat: render agent run monitor"
```

### Task 7: Full Verification

**Files:**
- No source file changes expected unless verification finds a defect.

- [ ] **Step 1: Run platform trace tests**

Run:

```powershell
.\mvnw -pl rs-service-platform-trace test
```

Expected: all tests pass.

- [ ] **Step 2: Run agent service focused tests**

Run:

```powershell
.\mvnw -pl rs-service-agent -Dtest=InMemoryAgentOrchestrationServiceTest,AgentTraceReporterConfigurationTest test
```

Expected: all tests pass.

- [ ] **Step 3: Run frontend typecheck and build**

Run from `java_agent/frontend`:

```powershell
npm run lint
npm run build
```

Expected: both commands pass.

- [ ] **Step 4: Manual smoke in mock mode**

Run from `java_agent/frontend`:

```powershell
npm run dev
```

Open `/observe`, enable mock mode if needed, query:

```text
Session ID: mock-session
Request ID: agent_req_mock_001
```

Expected:

- Summary shows `success`, token count, tool count, and zero errors.
- Timeline has at least one event.
- Clicking the event shows input summary, output summary, and raw JSON.
- Auto-refresh checkbox can be toggled and does not break the page.

- [ ] **Step 5: Commit verification fixes if any**

If verification required fixes:

```powershell
git add <fixed-files>
git commit -m "fix: stabilize agent run monitor"
```

If no fixes were required, do not create an empty commit.
