package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.SpringAiAgentToolCallbackFactory;
import org.junit.jupiter.api.Test;
import org.springframework.ai.tool.ToolCallback;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class SpringAiAgentToolCallbackFactoryTest {

    @Test
    void createsSpringAiToolCallbacksFromEnabledRuntimeTools() {
        SpringAiAgentToolCallbackFactory factory = new SpringAiAgentToolCallbackFactory(
                new InMemoryAgentRuntimeConfigurationService()
        );

        List<ToolCallback> callbacks = factory.createToolCallbacks();

        assertThat(callbacks)
                .extracting(callback -> callback.getToolDefinition().name())
                .contains("load_skill", "call_agent", "emit_final_answer");
        ToolCallback emitFinalAnswer = callbacks.stream()
                .filter(callback -> "emit_final_answer".equals(callback.getToolDefinition().name()))
                .findFirst()
                .orElseThrow();
        assertThat(emitFinalAnswer.getToolDefinition().description())
                .contains("final answer");
        assertThat(emitFinalAnswer.getToolDefinition().inputSchema())
                .contains("\"blocks\"")
                .contains("\"product_cards\"")
                .contains("\"followup_question\"");
    }

    @Test
    void callbackExecutionIsDeferredToAgentLoop() {
        SpringAiAgentToolCallbackFactory factory = new SpringAiAgentToolCallbackFactory(
                new InMemoryAgentRuntimeConfigurationService()
        );

        ToolCallback loadSkill = factory.createToolCallbacks().stream()
                .filter(callback -> "load_skill".equals(callback.getToolDefinition().name()))
                .findFirst()
                .orElseThrow();

        String result = loadSkill.call("{\"skill_name\":\"explicit-need-recommendation\"}");

        assertThat(result)
                .contains("\"status\":\"DEFERRED\"")
                .contains("\"tool_name\":\"load_skill\"")
                .contains("agent loop");
    }
}
