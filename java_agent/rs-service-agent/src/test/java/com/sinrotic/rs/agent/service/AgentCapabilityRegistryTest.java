package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.AgentCapabilityDescriptor;
import com.sinrotic.rs.agent.domain.AgentCapabilityRequest;
import com.sinrotic.rs.agent.domain.AgentCapabilityResult;
import com.sinrotic.rs.agent.domain.AgentRuntimeProfile;
import com.sinrotic.rs.agent.domain.AgentProfileFailurePolicy;
import com.sinrotic.rs.agent.domain.AgentPublicOutputBlock;
import com.sinrotic.rs.agent.domain.session.AgentSessionEvent;
import com.sinrotic.rs.agent.service.impl.AgentRagExplainCapability;
import com.sinrotic.rs.agent.service.impl.AgentRecommendationCapability;
import com.sinrotic.rs.agent.service.impl.AgentSessionMemoryCapability;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentCapabilityRegistry;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentHotSessionStore;
import com.sinrotic.rs.agent.service.impl.TraceReportingAgentCapabilityAuditSink;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.ArrayList;
import java.util.concurrent.atomic.AtomicBoolean;
import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

class AgentCapabilityRegistryTest {

    private static final AgentRuntimeProfile SHOPPING_PROFILE = new AgentRuntimeProfile(
            "shopping-assistant",
            "model/default",
            "prompt/default",
            List.of("recommend", "rag-explain", "session-memory"),
            List.of(AgentPublicOutputBlock.TEXT),
            8,
            AgentProfileFailurePolicy.FAIL_TURN
    );

    @Test
    void executesRegisteredCapabilityAllowedByProfile() {
        InMemoryAgentCapabilityRegistry registry = new InMemoryAgentCapabilityRegistry();
        registry.register(new TestCapability("recommend", true, request ->
                AgentCapabilityResult.success("recommend", Map.of("items", List.of("B001")))));

        AgentCapabilityResult result = registry.execute(SHOPPING_PROFILE,
                new AgentCapabilityRequest("req-1", "shopping-assistant", "recommend", Map.of("query", "backpack")));

        assertThat(result.status()).isEqualTo("SUCCESS");
        assertThat(result.payload()).containsEntry("items", List.of("B001"));
    }

    @Test
    void rejectsUnregisteredCapabilityBeforeAdapterExecution() {
        List<com.sinrotic.rs.agent.domain.AgentCapabilityAuditEvent> auditEvents = new ArrayList<>();
        InMemoryAgentCapabilityRegistry registry = new InMemoryAgentCapabilityRegistry(auditEvents::add);

        AgentCapabilityResult result = registry.execute(SHOPPING_PROFILE,
                new AgentCapabilityRequest("req-1", "shopping-assistant", "recommend", Map.of()));

        assertThat(result.status()).isEqualTo("FAILED");
        assertThat(result.errorCode()).isEqualTo("CAPABILITY_NOT_REGISTERED");
        assertThat(auditEvents).singleElement()
                .extracting(com.sinrotic.rs.agent.domain.AgentCapabilityAuditEvent::errorCode)
                .isEqualTo("CAPABILITY_NOT_REGISTERED");
    }

    @Test
    void projectsAuditEventToExistingTraceReporter() {
        List<com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO> traceEvents = new ArrayList<>();
        InMemoryAgentCapabilityRegistry registry = new InMemoryAgentCapabilityRegistry(
                new TraceReportingAgentCapabilityAuditSink(traceEvents::add)
        );

        registry.execute(SHOPPING_PROFILE,
                new AgentCapabilityRequest("req-1", "shopping-assistant", "recommend", Map.of()));

        assertThat(traceEvents).singleElement().satisfies(event -> {
            assertThat(event.eventType()).isEqualTo("capability_result");
            assertThat(event.toolName()).isEqualTo("recommend");
            assertThat(event.errorCode()).isEqualTo("CAPABILITY_NOT_REGISTERED");
        });
    }

    @Test
    void rejectsCapabilityNotAllowedByProfileBeforeAdapterExecution() {
        AtomicBoolean invoked = new AtomicBoolean();
        InMemoryAgentCapabilityRegistry registry = new InMemoryAgentCapabilityRegistry();
        registry.register(new TestCapability("session-memory", true, request -> {
            invoked.set(true);
            return AgentCapabilityResult.success("session-memory", Map.of());
        }));

        AgentRuntimeProfile restricted = new AgentRuntimeProfile(
                "restricted", "model/default", "prompt/default", List.of("recommend"),
                List.of(AgentPublicOutputBlock.TEXT), 4, AgentProfileFailurePolicy.FAIL_TURN);
        AgentCapabilityResult result = registry.execute(restricted,
                new AgentCapabilityRequest("req-1", "restricted", "session-memory", Map.of()));

        assertThat(result.errorCode()).isEqualTo("CAPABILITY_NOT_ALLOWED");
        assertThat(invoked).isFalse();
    }

    @Test
    void rejectsNonReplaySafeCapabilityBeforeAdapterExecution() {
        AtomicBoolean invoked = new AtomicBoolean();
        InMemoryAgentCapabilityRegistry registry = new InMemoryAgentCapabilityRegistry();
        registry.register(new TestCapability("recommend", false, request -> {
            invoked.set(true);
            return AgentCapabilityResult.success("recommend", Map.of());
        }));

        AgentCapabilityResult result = registry.execute(SHOPPING_PROFILE,
                new AgentCapabilityRequest("req-1", "shopping-assistant", "recommend", Map.of()));

        assertThat(result.errorCode()).isEqualTo("CAPABILITY_NOT_REPLAY_SAFE");
        assertThat(invoked).isFalse();
    }

    @Test
    void rejectsRequestBoundToAnotherProfile() {
        InMemoryAgentCapabilityRegistry registry = new InMemoryAgentCapabilityRegistry();
        registry.register(new TestCapability("recommend", true, request -> AgentCapabilityResult.success("recommend", Map.of())));

        AgentCapabilityResult result = registry.execute(SHOPPING_PROFILE,
                new AgentCapabilityRequest("req-1", "another-profile", "recommend", Map.of()));

        assertThat(result.errorCode()).isEqualTo("CAPABILITY_PROFILE_MISMATCH");
    }

    @Test
    void convertsAdapterFailureToStructuredResult() {
        InMemoryAgentCapabilityRegistry registry = new InMemoryAgentCapabilityRegistry();
        registry.register(new TestCapability("rag-explain", true, request -> {
            throw new IllegalStateException("downstream unavailable");
        }));

        AgentCapabilityResult result = registry.execute(SHOPPING_PROFILE,
                new AgentCapabilityRequest("req-1", "shopping-assistant", "rag-explain", Map.of()));

        assertThat(result.status()).isEqualTo("FAILED");
        assertThat(result.errorCode()).isEqualTo("CAPABILITY_EXECUTION_FAILED");
        assertThat(result.errorMessage()).contains("downstream unavailable");
    }

    @Test
    void exposesStableBuiltInCapabilityDescriptors() {
        assertThat(AgentCapabilityDefinitions.builtIns())
                .extracting(AgentCapabilityDescriptor::id)
                .containsExactlyInAnyOrder("recommend", "rag-explain", "session-memory");
        assertThat(AgentCapabilityDefinitions.builtIns())
                .allMatch(AgentCapabilityDescriptor::replaySafe);
    }

    @Test
    void mapsRagAdapterToExistingDelegateBoundary() {
        AtomicBoolean invoked = new AtomicBoolean();
        InMemoryAgentCapabilityRegistry registry = new InMemoryAgentCapabilityRegistry();
        registry.register(new AgentRagExplainCapability((requestId, agentName, arguments) -> {
            invoked.set(true);
            assertThat(agentName).isEqualTo("rag_agent");
            return Map.of("evidence", List.of("support-1"));
        }));

        AgentCapabilityResult result = registry.execute(SHOPPING_PROFILE,
                new AgentCapabilityRequest("req-1", "shopping-assistant", "rag-explain", Map.of("query", "why")));

        assertThat(result.status()).isEqualTo("SUCCESS");
        assertThat(result.payload()).containsKey("evidence");
        assertThat(invoked).isTrue();
    }

    @Test
    void mapsRecommendationAdapterToExistingRecommendationBoundary() {
        InMemoryAgentCapabilityRegistry registry = new InMemoryAgentCapabilityRegistry();
        registry.register(new AgentRecommendationCapability(request -> List.of(
                new com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO(
                        "B001", "Commuter Backpack", "Backpacks", 0.91, "matched")
        )));

        AgentCapabilityResult result = registry.execute(SHOPPING_PROFILE,
                new AgentCapabilityRequest("req-1", "shopping-assistant", "recommend",
                        Map.of("query", "backpack", "limit", 1)));

        assertThat(result.status()).isEqualTo("SUCCESS");
        assertThat((List<?>) result.payload().get("items")).hasSize(1);
    }

    @Test
    void mapsSessionMemoryToExistingHotStoreBoundary() {
        InMemoryAgentHotSessionStore store = new InMemoryAgentHotSessionStore();
        store.append(new AgentSessionEvent("evt-1", "session-1", "req-1", "turn_completed", 0,
                "", Map.of("text", "hello"), "", "", Instant.now()));
        InMemoryAgentCapabilityRegistry registry = new InMemoryAgentCapabilityRegistry();
        registry.register(new AgentSessionMemoryCapability(store));

        AgentCapabilityResult result = registry.execute(SHOPPING_PROFILE,
                new AgentCapabilityRequest("req-1", "shopping-assistant", "session-memory", Map.of("session_id", "session-1")));

        assertThat(result.status()).isEqualTo("SUCCESS");
        assertThat(result.payload()).containsEntry("event_count", 1);
    }

    private record TestCapability(
            String id,
            boolean replaySafe,
            java.util.function.Function<AgentCapabilityRequest, AgentCapabilityResult> handler
    ) implements AgentCapability {

        @Override
        public AgentCapabilityDescriptor descriptor() {
            return new AgentCapabilityDescriptor(id, id + " capability", Map.of("type", "object"), replaySafe, false);
        }

        @Override
        public AgentCapabilityResult execute(AgentCapabilityRequest request) {
            return handler.apply(request);
        }
    }
}
