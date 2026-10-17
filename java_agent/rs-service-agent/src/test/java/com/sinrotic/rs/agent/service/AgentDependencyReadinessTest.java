package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentTemplateProperties;
import com.sinrotic.rs.agent.service.impl.AgentDependencyReadiness;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.SpringAiAgentToolCallbackFactory;
import org.junit.jupiter.api.Test;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import static org.assertj.core.api.Assertions.assertThat;

class AgentDependencyReadinessTest {
    @Test
    void hiddenToolCannotReachDelegateEvenWhenModelStillRequestsIt() {
        var runtime = new InMemoryAgentRuntimeConfigurationService(new AgentTemplateProperties(), name -> !"call_agent".equals(name));
        AgentToolUseExecutor delegate = event -> { throw new AssertionError("unavailable dependency was invoked"); };
        var executor = new com.sinrotic.rs.agent.service.impl.AgentCapabilityToolUseExecutor(delegate, null, runtime);
        assertThat(executor.execute(com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent.toolUse("call_agent", java.util.Map.of())).join())
                .containsEntry("status", "FAILED").containsEntry("error_code", "TOOL_UNAVAILABLE");
    }
    @Test
    void outageHidesDependencyToolsAndReminderAndRecoveryRestoresSchemas() {
        var healthy = new AtomicBoolean(false);
        var calls = new AtomicInteger();
        var clock = new AtomicLong(1);
        var readiness = new AgentDependencyReadiness(() -> { calls.incrementAndGet(); return healthy.get(); }, clock::get, true);
        var runtime = new InMemoryAgentRuntimeConfigurationService(new AgentTemplateProperties(), readiness);
        var factory = new SpringAiAgentToolCallbackFactory(runtime);
        assertThat(factory.createToolCallbacks()).extracting(tool -> tool.getToolDefinition().name())
                .contains("load_skill", "emit_final_answer").doesNotContain("call_agent", "recommend_candidates", "rag_support");
        assertThat(runtime.runtimeContextMessages()).noneMatch(message -> message.contains("以下 agent"));
        assertThat(calls).hasValue(1);
        healthy.set(true);
        clock.addAndGet(1_000_000_001L);
        assertThat(factory.createToolCallbacks()).extracting(tool -> tool.getToolDefinition().name()).contains("call_agent");
        assertThat(factory.createToolCallbacks(true)).extracting(tool -> tool.getToolDefinition().name()).containsExactly("emit_final_answer");
        assertThat(calls).hasValue(2);
    }

    @Test
    void memoryRecommendationAndLocalOutputRemainAvailableDuringOutage() {
        var readiness = new AgentDependencyReadiness(() -> false, () -> 1L, false);
        assertThat(readiness.test("recommend_candidates")).isTrue();
        assertThat(readiness.test("emit_ui")).isTrue();
        assertThat(readiness.test("call_agent")).isFalse();
    }
}
