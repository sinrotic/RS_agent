package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.SpringAiAgentToolCallbackFactory;
import com.sinrotic.rs.agent.config.AgentTemplateProperties;
import com.sinrotic.rs.agent.domain.AgentProfileFailurePolicy;
import com.sinrotic.rs.agent.domain.AgentPublicOutputBlock;
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

    @Test
    void hidesCapabilitiesThatTheSelectedProfileDoesNotAllow() {
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
        SpringAiAgentToolCallbackFactory factory = new SpringAiAgentToolCallbackFactory(
                new InMemoryAgentRuntimeConfigurationService(properties)
        );

        assertThat(factory.createToolCallbacks())
                .extracting(callback -> callback.getToolDefinition().name())
                .contains("recommend_candidates")
                .doesNotContain("rag_support", "rag_evidence_search", "session_memory");
    }
}
