package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.AgentCapabilityResult;
import com.sinrotic.rs.agent.config.AgentTemplateProperties;
import com.sinrotic.rs.agent.domain.AgentProfileFailurePolicy;
import com.sinrotic.rs.agent.domain.AgentPublicOutputBlock;
import com.sinrotic.rs.agent.service.impl.AgentCapabilityToolUseExecutor;
import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentCapabilityRegistry;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import org.junit.jupiter.api.Test;

import java.util.Map;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.assertj.core.api.Assertions.assertThat;

class AgentCapabilityToolUseExecutorTest {

    @Test
    void routesMappedToolThroughCapabilityRegistry() {
        AtomicBoolean delegateInvoked = new AtomicBoolean();
        AgentToolUseExecutor delegate = event -> {
            delegateInvoked.set(true);
            return CompletableFuture.completedFuture(Map.of("status", "SUCCESS"));
        };
        InMemoryAgentCapabilityRegistry registry = new InMemoryAgentCapabilityRegistry();
        registry.register(new TestCapability("recommend"));
        AgentCapabilityToolUseExecutor executor = new AgentCapabilityToolUseExecutor(
                delegate, registry, new InMemoryAgentRuntimeConfigurationService());

        Map<String, Object> result = executor.execute(AgentModelStreamEvent.toolUse(
                "toolu-1", "recommend_candidates", Map.of("query", "backpack"))).join();

        assertThat(result).containsEntry("status", "SUCCESS").containsEntry("capability_id", "recommend");
        assertThat(delegateInvoked).isFalse();
    }

    @Test
    void rejectsUnknownToolBeforeDelegate() {
        AtomicBoolean delegateInvoked = new AtomicBoolean();
        AgentToolUseExecutor delegate = event -> {
            delegateInvoked.set(true);
            return CompletableFuture.completedFuture(Map.of("status", "SUCCESS"));
        };
        AgentCapabilityToolUseExecutor executor = new AgentCapabilityToolUseExecutor(
                delegate, new InMemoryAgentCapabilityRegistry(), new InMemoryAgentRuntimeConfigurationService());

        Map<String, Object> result = executor.execute(AgentModelStreamEvent.toolUse("toolu-1", "drop_database", Map.of())).join();

        assertThat(result).containsEntry("status", "FAILED").containsEntry("error_code", "TOOL_NOT_REGISTERED");
        assertThat(delegateInvoked).isFalse();
    }

    @Test
    void preservesInternalRegisteredToolExecution() {
        AtomicBoolean delegateInvoked = new AtomicBoolean();
        AgentToolUseExecutor delegate = event -> {
            delegateInvoked.set(true);
            return CompletableFuture.completedFuture(Map.of("status", "SUCCESS", "tool_name", event.toolName()));
        };
        AgentCapabilityToolUseExecutor executor = new AgentCapabilityToolUseExecutor(
                delegate, new InMemoryAgentCapabilityRegistry(), new InMemoryAgentRuntimeConfigurationService());

        Map<String, Object> result = executor.execute(AgentModelStreamEvent.toolUse("toolu-1", "load_skill", Map.of())).join();

        assertThat(result).containsEntry("status", "SUCCESS");
        assertThat(delegateInvoked).isTrue();
    }

    @Test
    void rejectsMappedCapabilityThatProfileDoesNotAllow() {
        InMemoryAgentCapabilityRegistry registry = new InMemoryAgentCapabilityRegistry();
        registry.register(new TestCapability("rag-explain"));
        AgentCapabilityToolUseExecutor executor = new AgentCapabilityToolUseExecutor(
                event -> CompletableFuture.completedFuture(Map.of("status", "SUCCESS")),
                registry,
                new InMemoryAgentRuntimeConfigurationService(recommendOnlyProperties())
        );

        Map<String, Object> result = executor.execute(AgentModelStreamEvent.toolUse(
                "toolu-1", "rag_support", Map.of("query", "backpack"))).join();

        assertThat(result)
                .containsEntry("status", "FAILED")
                .containsEntry("capability_id", "rag-explain")
                .containsEntry("error_code", "CAPABILITY_NOT_ALLOWED");
    }

    private AgentTemplateProperties recommendOnlyProperties() {
        AgentTemplateProperties.Profile profile = new AgentTemplateProperties.Profile();
        profile.setId("recommend-only");
        profile.setModelRef("default");
        profile.setSystemPromptRef("default");
        profile.setAllowedCapabilities(List.of("recommend"));
        profile.setAllowedOutputBlocks(List.of(AgentPublicOutputBlock.TEXT));
        profile.setMaxLoops(3);
        profile.setFailurePolicy(AgentProfileFailurePolicy.FAIL_TURN);
        AgentTemplateProperties properties = new AgentTemplateProperties();
        properties.setDefaultProfile("recommend-only");
        properties.setProfiles(List.of(profile));
        return properties;
    }

    private record TestCapability(String id) implements AgentCapability {

        @Override
        public com.sinrotic.rs.agent.domain.AgentCapabilityDescriptor descriptor() {
            return AgentCapabilityDefinitions.byId(id);
        }

        @Override
        public AgentCapabilityResult execute(com.sinrotic.rs.agent.domain.AgentCapabilityRequest request) {
            return AgentCapabilityResult.success(id, Map.of("accepted", true));
        }
    }
}
