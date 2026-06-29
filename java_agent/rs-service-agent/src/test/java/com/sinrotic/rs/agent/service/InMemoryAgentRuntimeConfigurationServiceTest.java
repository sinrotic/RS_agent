package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSkillUpsertDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSystemPromptUpdateDTO;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeToolUpsertDTO;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class InMemoryAgentRuntimeConfigurationServiceTest {

    @Test
    void loadsBuiltInSkillsAndDefaultToolsForRuntimeMetadata() {
        InMemoryAgentRuntimeConfigurationService service = new InMemoryAgentRuntimeConfigurationService();

        assertThat(service.systemPrompt().content()).contains("recommendation");
        assertThat(service.skills()).extracting("name")
                .contains(
                        "explicit-need-recommendation",
                        "unclear-need-clarification",
                        "cold-user-onboarding",
                        "feedback-adaptation",
                        "evidence-grounded-explanation"
                );
        assertThat(service.skill("explicit-need-recommendation").content()).contains("Workflow");
        assertThat(service.tools()).extracting("name")
                .contains(
                        "load_skill",
                        "call_agent",
                        "emit_final_answer",
                        "render_product_cards",
                        "recommend_candidates",
                        "recommend_semantic_recall",
                        "recommend_profile_pipeline",
                        "recommend_cold_fallback",
                        "recommend_rerank_candidates",
                        "rag_support",
                        "catalog_card"
                );
    }

    @Test
    void customSkillAndToolDefinitionsOverrideRuntimeMetadata() {
        InMemoryAgentRuntimeConfigurationService service = new InMemoryAgentRuntimeConfigurationService();

        service.updateSystemPrompt(new AgentRuntimeSystemPromptUpdateDTO(
                "experiment-a",
                "Always cite tool evidence."
        ));
        service.upsertSkill("explicit-need-recommendation", new AgentRuntimeSkillUpsertDTO(
                "Custom trigger",
                "---\nname: explicit-need-recommendation\n---\n# Custom workflow\n",
                true
        ));
        service.upsertTool("recommend_candidates", new AgentRuntimeToolUpsertDTO(
                "rs-service-recommend",
                "Custom candidate retriever.",
                false,
                Map.of("type", "object", "properties", Map.of("limit", Map.of("type", "integer")))
        ));

        assertThat(service.systemPrompt().name()).isEqualTo("experiment-a");
        assertThat(service.skill("explicit-need-recommendation").description()).isEqualTo("Custom trigger");
        assertThat(service.skill("explicit-need-recommendation").source()).isEqualTo("custom");
        assertThat(service.tools().stream()
                .filter(tool -> "recommend_candidates".equals(tool.name()))
                .findFirst()
                .orElseThrow()
                .enabled()).isFalse();
    }

    @Test
    void modelContextIncludesSkillAndAgentListingsButOmitsCoreToolListingByDefault() {
        InMemoryAgentRuntimeConfigurationService service = new InMemoryAgentRuntimeConfigurationService();

        Map<String, Object> context = service.modelContext();

        assertThat(context).containsKey("runtime_context_messages");
        assertThat((Iterable<?>) context.get("runtime_context_messages"))
                .anySatisfy(message -> assertThat((String) message)
                        .contains("<system-reminder>")
                        .contains("The following skills are available for use with the load_skill tool:")
                        .contains("- explicit-need-recommendation:")
                        .contains("</system-reminder>"))
                .anySatisfy(message -> assertThat((String) message)
                        .contains("<system-reminder>")
                        .contains("The following agents are available through the call_agent tool:")
                        .contains("- rag_agent:")
                        .contains("</system-reminder>"));
        assertThat((Iterable<?>) context.get("runtime_context_messages"))
                .noneSatisfy(message -> assertThat((String) message)
                        .contains("The following extension tools are available:"));
    }

    @Test
    void extensionToolListingCanBeEnabledForToolSearchStyleDiscovery() {
        InMemoryAgentRuntimeConfigurationService service = new InMemoryAgentRuntimeConfigurationService();
        service.setExtensionToolListingEnabled(true);

        Map<String, Object> context = service.modelContext();

        assertThat((Iterable<?>) context.get("runtime_context_messages"))
                .anySatisfy(message -> assertThat((String) message)
                        .contains("<system-reminder>")
                        .contains("The following extension tools are available:")
                        .contains("- recommend_semantic_recall:")
                        .contains("- recommend_profile_pipeline:")
                        .contains("- recommend_cold_fallback:")
                        .contains("- recommend_rerank_candidates:")
                        .contains("</system-reminder>"));
    }
}
